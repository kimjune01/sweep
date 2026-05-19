"""reinvestigate_prep -- hoist CI failure context for the engagement lane.

investigate_prep handles the production-lane shape: "given an issue,
investigate the bug." reinvestigate is a different shape: "this PR's
CI just went red, look at the failure logs and figure out what broke."

The gh calls are different too:
  - gh run list / gh run view <id>         -- failing workflow runs
  - gh api repos/X/actions/jobs/<id>/logs  -- the actual error output
  - gh api repos/X/commits/<sha>/check-runs -- check-run detail
  - gh pr view <pr> --json comments,reviews -- new reviewer context

Pre-fetching these into the pack drops reinvestigate's invisible-
subprocess gh footprint the same way investigate_prep did for the
production lane. Same INVESTIGATE_CONTEXT env-var mechanism; the
skill markdown branches on what the pack contains.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

from sweep import gh_io


_LOG_TAIL_LINES = 500  # per failing job; the error is usually at the end


def _safe(s: str | None, default: str = "(none)") -> str:
    return s if s else default


def _truncate(s: str, max_chars: int = 6000) -> str:
    if len(s) <= max_chars:
        return s
    return s[:max_chars] + f"\n\n... [truncated, original was {len(s)} chars]"


def _gh(args: list[str], timeout: int = 15) -> str:
    """Direct gh shellout for log fetching. Bypasses gh_io cache because
    logs are large and per-run unique; caching them would bloat the
    cache without reuse benefit."""
    try:
        r = subprocess.run(
            ["gh", *args], capture_output=True, text=True, timeout=timeout,
        )
        if r.returncode != 0:
            return f"(gh {' '.join(args)} failed rc={r.returncode}: {(r.stderr or '')[:200]})"
        return r.stdout or ""
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return f"(gh {' '.join(args)} errored: {type(e).__name__})"


def prepare_reinvestigate_context(repo: str, pr: int) -> str:
    """Return a markdown context pack for the reinvestigate skill.

    Five sections:
      1. PR header (title, head branch, head SHA, mergeable, draft)
      2. Failing checks summary (names + conclusions + URLs)
      3. Per-failing-job log tail (~500 lines each)
      4. Recent commits on the head branch
      5. New comments/reviews on the PR

    Each section degrades to a stub on failure so the pack always parses."""
    parts: list[str] = [f"# Reinvestigate context: {repo}#{pr}", ""]

    # 1. PR header — most fields cached by gh_io.
    try:
        pr_data = gh_io.pr_view(
            repo, pr,
            fields="number,title,headRefName,headRefOid,isDraft,"
                   "mergeable,reviewDecision,statusCheckRollup,updatedAt",
        )
    except Exception as e:
        pr_data = {}
        parts.append(f"## PR\n\n(pr_view failed: {type(e).__name__}: {e})\n")
    head_sha = ""
    head_branch = ""
    if pr_data:
        title = _safe(pr_data.get("title"))
        head_branch = _safe(pr_data.get("headRefName"))
        head_sha = (pr_data.get("headRefOid") or "")[:12]
        parts.append(f"## PR: {title}")
        parts.append("")
        parts.append(f"- **head branch**: `{head_branch}`")
        parts.append(f"- **head SHA**: `{head_sha}`")
        parts.append(f"- **draft**: {pr_data.get('isDraft', False)}")
        parts.append(f"- **mergeable**: {pr_data.get('mergeable', '?')}")
        parts.append(f"- **review decision**: {pr_data.get('reviewDecision', '(none)')}")
        parts.append(f"- **updated**: {pr_data.get('updatedAt', '?')}")
        parts.append("")

    # 2. Failing checks summary (from rollup) + per-job log tails.
    rollup = pr_data.get("statusCheckRollup") or []
    failing = [c for c in rollup
               if (c.get("conclusion") == "FAILURE" or c.get("conclusion") == "FAILED")]
    parts.append(f"## Failing checks ({len(failing)} of {len(rollup)})")
    parts.append("")
    if not failing:
        parts.append("(no failing checks at the moment — CI may have recovered or "
                     "rollup is stale)")
        parts.append("")
    else:
        for c in failing[:20]:
            name = c.get("name") or c.get("context") or "?"
            url = c.get("detailsUrl") or c.get("targetUrl") or "?"
            parts.append(f"- **{name}** ({c.get('conclusion', '?')}) -- {url}")
        parts.append("")

        # 3. Per-failing-job log tails. detailsUrl points to a run-log
        # endpoint; gh run view + gh run view --log can pull. We use the
        # actions/jobs/<id>/logs API when we can parse the job id out.
        parts.append("## Failing job logs (tail)")
        parts.append("")
        for c in failing[:5]:  # cap at 5 to bound pack size
            name = c.get("name") or c.get("context") or "?"
            url = c.get("detailsUrl") or c.get("targetUrl") or ""
            # detailsUrl shape: .../actions/runs/<run_id>/job/<job_id>
            m = re.search(r"/actions/runs/(\d+)/job/(\d+)", url)
            parts.append(f"### {name}")
            parts.append("")
            if not m:
                parts.append(f"(no parseable run/job id from {url!r})")
                parts.append("")
                continue
            run_id, job_id = m.group(1), m.group(2)
            log_text = _gh(
                ["api", f"repos/{repo}/actions/jobs/{job_id}/logs"],
                timeout=20,
            )
            tail = "\n".join(log_text.splitlines()[-_LOG_TAIL_LINES:])
            parts.append("```")
            parts.append(_truncate(tail, 8000))
            parts.append("```")
            parts.append("")

    # 4. Recent commits on the branch (head + 5 prior).
    if head_branch:
        parts.append(f"## Recent commits on `{head_branch}` (last 5)")
        parts.append("")
        try:
            commits = gh_io.api(
                f"repos/{repo}/commits?sha={head_branch}&per_page=5",
                ttl=60,
            )
            if isinstance(commits, list):
                for cm in commits:
                    sha = (cm.get("sha") or "")[:12]
                    msg = ((cm.get("commit") or {}).get("message")
                           or "").splitlines()[0][:120]
                    author = ((cm.get("commit") or {}).get("author") or {}).get("name", "?")
                    parts.append(f"- `{sha}` {author}: {msg}")
            else:
                parts.append("(commits lookup returned non-list)")
        except Exception as e:
            parts.append(f"(commits lookup failed: {type(e).__name__})")
        parts.append("")

    # 5. New comments + reviews since this reinvestigate was queued.
    parts.append("## Recent PR comments + reviews (last 5)")
    parts.append("")
    try:
        comments = gh_io.api(
            f"repos/{repo}/issues/{pr}/comments?per_page=5",
            ttl=60,
        )
        if isinstance(comments, list) and comments:
            for c in comments[-5:]:
                login = (c.get("user") or {}).get("login", "?")
                ts = c.get("created_at", "?")
                body = _truncate(_safe(c.get("body"), "(empty)"), 600)
                parts.append(f"**{login}** ({ts}):")
                parts.append("")
                parts.append(body)
                parts.append("")
        else:
            parts.append("(no recent comments)")
    except Exception as e:
        parts.append(f"(comments lookup failed: {type(e).__name__})")
    parts.append("")

    parts.append("---")
    parts.append("")
    parts.append(
        "**Note to skill:** this is a REINVESTIGATE cycle on a PR whose "
        "CI went red. Focus on the failing-job logs above; the original "
        "issue context (if relevant) is one level up but the immediate "
        "task is figuring out what broke in CI. Do NOT re-fetch run logs "
        "or check-runs -- they are here. Use `gh` only for things not in "
        "this pack (e.g. specific file blobs at the head SHA, individual "
        "review threads on a specific line)."
    )
    return "\n".join(parts)


def write_reinvestigate_context_pack(repo: str, pr: int, msg_id: str) -> Path:
    """Build the reinvestigate pack and write it to a temp file."""
    body = prepare_reinvestigate_context(repo, pr)
    safe_msg = re.sub(r"[^A-Za-z0-9_.-]", "_", msg_id)[:64]
    p = Path(tempfile.gettempdir()) / f"reinv-ctx-{safe_msg}.md"
    p.write_text(body)
    return p
