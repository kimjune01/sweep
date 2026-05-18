"""investigate_prep -- hoist deterministic gh calls out of /investigate.

The /investigate skill historically did its own gh fetches (issue view,
related PRs, self-PR history, CI status). That worked but had three
costs:

1. Budget opacity. Skill-side `gh` calls happen in the subprocess,
   not in our gh_io wrapper, so they bypass the cache and bypass the
   per-actor counter. SUBPROCESS_ESTIMATE was a flat charge calibrated
   for opus-era fan-out; codex-era was different; we never measured.

2. Variance. The skill might forget to check related PRs, or fetch
   them differently each time. Two investigate runs on the same issue
   could see different context just because the LLM made different
   tool-use decisions.

3. Latency. Each tool-use round-trip is "LLM thinks, shells out, waits,
   resumes." For ~6 calls this is meaningful versus pre-fetching all
   six in parallel before the skill starts.

This module gathers the deterministic context into one markdown blob
written to /tmp/inv-ctx-<msg_id>.md. The path is exported via the
INVESTIGATE_CONTEXT env var to the skill subprocess. The skill is
instructed (in its markdown) to read the pack and avoid re-fetching
what's in it.

What's pre-fetched:
  - Issue: title, body, labels, comments (last 5)
  - Related open PRs: keyword search by issue title
  - Self-PR history: any of operator's PRs against this repo
  - Default branch + CI status

What stays in the skill:
  - Reading specific source files (depends on the hypothesis)
  - Running tests
  - Anything not in the pre-fetched fields
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

from sweep import gh_io


def _safe(s: str | None, default: str = "(none)") -> str:
    return s if s else default


def _truncate(s: str, max_chars: int = 4000) -> str:
    if len(s) <= max_chars:
        return s
    return s[:max_chars] + f"\n\n... [truncated, original was {len(s)} chars]"


def _keywords_from_title(title: str, n: int = 3) -> list[str]:
    """Pull the most-distinctive words from the issue title for the
    related-PR search. Strips short/common words; keeps the top n
    unique tokens preserving order. Used to seed the gh pr search."""
    stop = {"the", "a", "an", "and", "or", "of", "in", "on", "for",
            "to", "is", "with", "when", "fix", "bug", "issue", "error",
            "fails", "fail", "broken", "not", "from", "by", "as", "at"}
    words = re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", title or "")
    out: list[str] = []
    seen: set[str] = set()
    for w in words:
        wl = w.lower()
        if wl in stop or wl in seen:
            continue
        seen.add(wl)
        out.append(w)
        if len(out) >= n:
            break
    return out


def _git_user() -> str:
    """Resolve the operator's gh login for self-PR history."""
    try:
        r = subprocess.run(
            ["gh", "api", "user", "--jq", ".login"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return "kimjune01"  # known default; falls back if gh whoami fails


def prepare_investigate_context(repo: str, issue: int) -> str:
    """Return a markdown context pack the /investigate skill can read.
    Five sections; each section degrades to a stub on failure so the
    pack always parses. All gh fetches go through gh_io (cached + per-
    actor budgeted)."""
    parts: list[str] = [f"# Investigate context: {repo}#{issue}", ""]

    # 1. Issue body + recent comments.
    try:
        issue_data = gh_io.issue_view(repo, issue)
    except Exception as e:
        issue_data = {}
        parts.append(f"## Issue\n\n(fetch failed: {type(e).__name__}: {e})\n")
    if issue_data:
        title = _safe(issue_data.get("title"))
        body = _truncate(_safe(issue_data.get("body"), "(empty body)"), 3000)
        labels = ", ".join(
            l.get("name", "") for l in (issue_data.get("labels") or [])
        ) or "(none)"
        author = (issue_data.get("author") or {}).get("login", "?")
        created = issue_data.get("createdAt", "?")
        parts.append(f"## Issue: {title}")
        parts.append("")
        parts.append(f"- **author**: {author}")
        parts.append(f"- **labels**: {labels}")
        parts.append(f"- **created**: {created}")
        parts.append("")
        parts.append("### Body")
        parts.append("")
        parts.append(body)
        parts.append("")
        comments = (issue_data.get("comments") or [])[-5:]
        if comments:
            parts.append("### Recent comments (last 5)")
            parts.append("")
            for c in comments:
                login = (c.get("author") or {}).get("login", "?")
                ts = c.get("createdAt", "?")
                cbody = _truncate(_safe(c.get("body"), "(empty)"), 600)
                parts.append(f"**{login}** ({ts}):")
                parts.append("")
                parts.append(cbody)
                parts.append("")

    # 2. Related open PRs via keyword search on title.
    keywords = _keywords_from_title(issue_data.get("title", ""))
    if keywords:
        query = " ".join(keywords[:2])
        parts.append(f"## Related open PRs (search: {query!r})")
        parts.append("")
        try:
            related = gh_io.pr_list(repo, state="open", limit=5)
            matched = [p for p in related
                       if any(k.lower() in (p.get("title", "") or "").lower()
                              for k in keywords)]
            if matched:
                for p in matched[:5]:
                    parts.append(
                        f"- #{p.get('number')} {p.get('title', '')} "
                        f"(by {(p.get('author') or {}).get('login', '?')})"
                    )
            else:
                parts.append("- (none matched)")
        except Exception as e:
            parts.append(f"- (lookup failed: {type(e).__name__})")
        parts.append("")

    # 3. Self-PR history on this repo (ship-guard signal).
    user = _git_user()
    parts.append(f"## Operator PR history ({user} on {repo})")
    parts.append("")
    try:
        own = gh_io.pr_list(repo, state="all", limit=10)
        own_mine = [p for p in own
                    if (p.get("author") or {}).get("login", "") == user]
        if own_mine:
            for p in own_mine[:10]:
                state = p.get("state", "?")
                parts.append(
                    f"- #{p.get('number')} [{state}] {p.get('title', '')}"
                )
        else:
            parts.append(f"- (no prior PRs by {user})")
    except Exception as e:
        parts.append(f"- (lookup failed: {type(e).__name__})")
    parts.append("")

    # 4. Default branch + CI status on it.
    try:
        repo_meta = gh_io.api(f"repos/{repo}", ttl=3600)
        default_branch = (repo_meta or {}).get("default_branch", "main")
    except Exception:
        default_branch = "main"
    parts.append(f"## Default branch: `{default_branch}`")
    parts.append("")
    try:
        ci = gh_io.default_branch_failing_checks(repo)
        failing = ci.get("failing_checks") or []
        if failing:
            parts.append(f"**Failing checks on {default_branch}:**")
            for c in failing[:10]:
                parts.append(f"- {c}")
        else:
            parts.append(f"All checks passing on {default_branch}.")
    except Exception as e:
        parts.append(f"(ci lookup failed: {type(e).__name__})")
    parts.append("")

    parts.append("---")
    parts.append("")
    parts.append(
        "**Note to skill:** the above is pre-fetched. Do NOT re-call "
        "`gh issue view`, `gh pr list`, or related-PR / self-history "
        "searches — that information is here. Use `gh` only for "
        "things not in this pack (e.g. `gh api repos/X/contents/path`)."
    )
    return "\n".join(parts)


def write_context_pack(repo: str, issue: int, msg_id: str) -> Path:
    """Build the context pack and write it to a temp file. Returns the
    path; the caller sets INVESTIGATE_CONTEXT=<path> on the subprocess."""
    body = prepare_investigate_context(repo, issue)
    safe_msg = re.sub(r"[^A-Za-z0-9_.-]", "_", msg_id)[:64]
    p = Path(tempfile.gettempdir()) / f"inv-ctx-{safe_msg}.md"
    p.write_text(body)
    return p
