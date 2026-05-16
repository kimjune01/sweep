"""`sweep pr <repo>#<pr>` — per-PR drill-down view.

Same visual register as `sweep cockpit` and `sweep lanes`: one screen of
markdown, truncated sections, trailing `| <command>` pointers to the
full detail. Read-only.

Layout:

  title + URL                       — `gh pr view ...`
  ---
  hypothesis bullets (terse)        — `cat ~/.sweep/repo-hypotheses/...`
  ---
  ## state                          — ci / review / mergeable / draft / stale
  ## origin                         — issue refs from PR body + hypothesis path
  ## receipts (N of M)              — last few attestation rows for this PR
  ## events (N of M)                — last few observe events touching this PR

Pointers cap each section so the operator knows where to dig further.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
from pathlib import Path

import typer

from sweep import gh_io, observe


# How many bullets / rows each truncated section shows before pointing
# the operator at the full detail command.
HYPOTHESIS_BULLETS = 6
RECEIPTS_LIMIT = 3
EVENTS_LIMIT = 4

REPOS_DIR = Path.home() / ".sweep" / "repo-hypotheses"
ATTESTATIONS_DIR = Path.home() / ".sweep" / "attestations"

REF_RE = re.compile(r"(?:closes|fixes|resolves|fix|close|resolve)\s+#(\d+)",
                    re.IGNORECASE)
PR_ARG_RE = re.compile(r"^([\w.-]+/[\w.-]+)#(\d+)$")


def register(app: typer.Typer) -> None:
    """Attach the pr command to a top-level Typer app."""
    app.command("pr")(pr_view)


def pr_view(
    ref: str = typer.Argument(..., help="owner/repo#N"),
) -> None:
    """Per-PR drill-down — title, hypothesis, state, origin, receipts, events."""
    m = PR_ARG_RE.match(ref)
    if not m:
        raise typer.BadParameter(
            f"expected owner/repo#N, got {ref!r}",
        )
    repo, pr = m.group(1), int(m.group(2))

    data = _fetch_pr(repo, pr)
    _render(repo, pr, data)


# ---------------------------------------------------------------- fetch


def _fetch_pr(repo: str, pr: int) -> dict:
    """Pull PR state via gh_io with the fields the view needs."""
    fields = (
        "state,mergeable,reviewDecision,statusCheckRollup,isDraft,"
        "headRefName,updatedAt,title,url,body"
    )
    try:
        data = gh_io.pr_view(repo, pr, fields=fields, ttl=60)
    except subprocess.CalledProcessError as e:
        raise typer.Exit(1) from e
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------- render


def _render(repo: str, pr: int, data: dict) -> None:
    title = data.get("title") or "(no title)"
    url = data.get("url") or f"https://github.com/{repo}/pull/{pr}"

    msg_ids = _msg_ids_for(repo, pr)
    artifacts = _artifacts_for(msg_ids)
    verdict = _latest_qa_verdict(repo, pr) if artifacts else None
    attested = bool(artifacts) and verdict == "pass"

    print(f"# {repo}#{pr} — {title}")
    print()

    # Each row is a user-intent label on the left and the resolution on
    # the right. Skip rows whose data side is empty so quiet PRs read
    # tight. "Do now" appears ONLY when something blocks the machine's
    # automatic flow — attested→drip→ship is routine and silent; humans
    # handle the exceptions.
    rows: list[tuple[str, str]] = []
    do_now = _do_now(url, artifacts, verdict, data)
    if do_now:
        rows.append(("Do now", do_now))
    rows.append(("GitHub", _github_cell(url, data)))

    hypothesis = _hypothesis_cell(repo)
    if hypothesis:
        rows.append(("Hypothesis", hypothesis))

    origin = _origin_cell(repo, data)
    if origin:
        rows.append(("Origin", origin))

    rows.append(("Artifacts", _receipts_cell(msg_ids, artifacts, attested)))

    timeline = _timeline_cell(repo, pr)
    if timeline:
        rows.append(("Timeline", timeline))

    _render_table(rows)


# ---------------------------------------------------------------- sections


def _hypothesis_path(repo: str) -> Path:
    slug = repo.replace("/", "-")
    return REPOS_DIR / f"{slug}.md"


def _render_table(rows: list[tuple[str, str]]) -> None:
    """Two-column markdown table. Left column is intent labels; right is
    the data resolving that intent. No header row — labels carry the
    column meaning by themselves."""
    if not rows:
        return
    print("|     |     |")
    print("| --- | --- |")
    for label, content in rows:
        print(f"| {label} | {content} |")


def _hypothesis_cell(repo: str) -> str:
    """Condense the hypothesis bullets into one table cell with a trailing
    file:// link to the full graph. Bullets are joined with ` · ` so the
    cell stays single-line. Empty cell → row hidden."""
    path = _hypothesis_path(repo)
    if not path.exists():
        return ""
    bullets = _extract_bullets(path)
    if not bullets:
        return ""
    shown = bullets[:HYPOTHESIS_BULLETS]
    body = " · ".join(shown)
    extra = len(bullets) - HYPOTHESIS_BULLETS
    if extra > 0:
        body += f" · _+{extra} more_"
    body += f" · [Hypothesis Graph]({path.as_uri()})"
    return body


def _extract_bullets(path: Path) -> list[str]:
    """Pull lines that start with '- ' from the hypothesis file, strip
    markdown emphasis, and condense whitespace. Caps at 20 raw bullets
    to keep memory bounded for huge hypotheses."""
    try:
        text = path.read_text()
    except OSError:
        return []
    bullets: list[str] = []
    for line in text.splitlines():
        ln = line.strip()
        if not ln.startswith("- "):
            continue
        body = ln[2:].strip()
        # Strip leading **Label**: bolding and condense whitespace.
        body = re.sub(r"^\*\*(.+?)\*\*:\s*", r"\1: ", body)
        body = " ".join(body.split())
        if body:
            bullets.append(body)
        if len(bullets) >= 20:
            break
    return bullets


CI_GLYPHS = {
    "green":   "✅",
    "failing": "❌",
    "pending": "⏳",
    "mixed":   "🟡",
    "unknown": "❓",
}
REVIEW_GLYPHS = {
    "APPROVED":          "👍 approved",
    "CHANGES_REQUESTED": "🛑 changes",
    "REVIEW_REQUIRED":   "👀 review",
}
MERGE_GLYPHS = {
    "MERGEABLE":   "🟢 mergeable",
    "CONFLICTING": "🔀 conflict",
    "UNKNOWN":     "❓ unknown",
}


def _do_now(url: str, artifacts: list[tuple[str, Path]],
             verdict: str | None, data: dict) -> str:
    """The next move ONLY when something blocks the machine's automatic
    flow. Attested PRs automatically go attested → drip → ship; nothing
    for the human to do. Human attention is reserved for exceptions:
    cascade failures, conflicts, maintainer engagement, force-push
    requirements.

    Priority order (first match wins):
      conflict        rebase needed (force-push)
      review changes  maintainer pushed back, needs a response
      cascade failed  receipts exist but verdict isn't pass — inspect

    Returns "" when nothing is blocked. ⛩️ and 🚧 are reserved for the
    attestation state, never used here; Do now is action verbs only."""
    if data.get("mergeable") == "CONFLICTING":
        return f"[Rebase]({url})"
    if data.get("reviewDecision") == "CHANGES_REQUESTED":
        return f"[Respond]({url})"
    if artifacts and verdict in {"fail", "partial", "revise"}:
        latest = artifacts[0][1]
        return f"[Inspect cascade]({latest.as_uri()})"
    return ""


def _github_cell(url: str, data: dict) -> str:
    """Right-hand side of the GitHub row: PR link + remote stats. CI,
    review decision, mergeable, draft, stale — facts GitHub owns."""
    ci_key = _ci_status(data.get("statusCheckRollup") or [])
    review = data.get("reviewDecision") or ""
    merge = data.get("mergeable") or ""

    cells = [f"[#{data.get('number') or '?'}]({url})"] if False else [f"<{url}>"]
    cells.append(f"{CI_GLYPHS.get(ci_key, '·')} {ci_key}")
    if review:
        cells.append(REVIEW_GLYPHS.get(review, f"· {review}"))
    if merge:
        cells.append(MERGE_GLYPHS.get(merge, f"· {merge}"))
    if data.get("isDraft"):
        cells.append("📝 draft")
    cells.append(_stale(data.get("updatedAt", "")))
    return " · ".join(cells)


def _ci_status(rollup: list[dict]) -> str:
    if not rollup:
        return "unknown"
    if any(c.get("conclusion") == "FAILURE" for c in rollup):
        return "failing"
    if any(c.get("status") != "COMPLETED" for c in rollup):
        return "pending"
    if all(c.get("conclusion") == "SUCCESS" for c in rollup):
        return "green"
    return "mixed"


def _stale(updated: str) -> str:
    if not updated:
        return "—"
    try:
        t = dt.datetime.fromisoformat(updated.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return "—"
    secs = (dt.datetime.now(dt.timezone.utc) - t).total_seconds()
    if secs < 60:
        return f"{int(secs)}s stale"
    if secs < 3600:
        return f"{int(secs // 60)}m stale"
    if secs < 86400:
        return f"{int(secs // 3600)}h stale"
    return f"{int(secs // 86400)}d stale"


def _origin_cell(repo: str, data: dict) -> str:
    """Issue refs parsed from the PR body, linked. Empty string if none."""
    body = data.get("body") or ""
    refs = sorted(set(int(n) for n in REF_RE.findall(body)))
    if not refs:
        return ""
    first = refs[0]
    url = f"https://github.com/{repo}/issues/{first}"
    more = f" · _+{len(refs)-1} more_" if len(refs) > 1 else ""
    return f"[issue #{first}]({url}){more}"


def _latest_qa_verdict(repo: str, pr: int) -> str | None:
    """Return the verdict of the most recent qa_converged event for this
    repo+pr, or None if no qa_converged event has fired yet."""
    if not observe.EVENTS.exists():
        return None
    try:
        for line in reversed(observe.EVENTS.read_text().splitlines()):
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (ev.get("kind") == "qa_converged"
                    and ev.get("repo") == repo
                    and ev.get("pr") == pr):
                return ev.get("verdict")
    except OSError:
        return None
    return None


def _artifacts_for(msg_ids: list[str]) -> list[tuple[str, Path]]:
    """Collect attestation artifact files across the given msg_ids,
    sorted newest-first per directory. Returns (msg_id, path) tuples."""
    artifacts: list[tuple[str, Path]] = []
    for msg_id in msg_ids:
        d = ATTESTATIONS_DIR / msg_id
        if not d.is_dir():
            continue
        for p in sorted(d.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            artifacts.append((msg_id, p))
    return artifacts


def _receipts_cell(msg_ids: list[str], artifacts: list[tuple[str, Path]],
                    attested: bool) -> str:
    """⛩️/🚧 badge + linked artifact filenames. Attestation status IS an
    artifact — the badge text links to the attestation directory when
    evidence exists, so a single click takes the operator from "is it
    attested?" to "show me the proof."

    Two delimiters in the cell, by role:
      ` ┊ `  major break, status → evidence
      ` · `  minor, between files

    Empty artifact set → just the 🚧 Unattested badge, no link (no
    evidence to point at yet)."""
    icon = "⛩️" if attested else "🚧"
    label = "Attested" if attested else "Unattested"
    if not artifacts:
        return f"{icon} {label}"
    # Evidence dir link doubles as the badge href — clicking the badge
    # opens the folder of receipts that establish (or fail to establish)
    # the attestation claim. Same link used by [+N more] overflow tail.
    dir_link = (ATTESTATIONS_DIR / msg_ids[0]).as_uri()
    badge = f"{icon} [{label}]({dir_link})"
    shown = artifacts[:RECEIPTS_LIMIT]
    files = [f"[{p.name}]({p.as_uri()})" for _msg_id, p in shown]
    extra = len(artifacts) - RECEIPTS_LIMIT
    if extra > 0:
        files.append(f"[+{extra} more]({dir_link})")
    return f"{badge} ┊ {' · '.join(files)}"


def _msg_ids_for(repo: str, pr: int) -> list[str]:
    """Find msg_ids touching this repo+pr by scanning events.jsonl
    (newest first). De-duplicated, capped."""
    if not observe.EVENTS.exists():
        return []
    seen: list[str] = []
    seen_set: set[str] = set()
    try:
        for line in reversed(observe.EVENTS.read_text().splitlines()):
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("repo") != repo or ev.get("pr") != pr:
                continue
            mid = ev.get("msg_id")
            if mid and mid not in seen_set:
                seen.append(mid)
                seen_set.add(mid)
            if len(seen) >= 10:
                break
    except OSError:
        return []
    return seen


def _timeline_cell(repo: str, pr: int) -> str:
    """Recent events touching this PR, formatted compact: `5/15 5:30p
    kind · extras`. Joined by ` · `. Tail link to `sweep observe events`
    for the full feed."""
    rows: list[dict] = []
    if not observe.EVENTS.exists():
        return ""
    try:
        for line in reversed(observe.EVENTS.read_text().splitlines()):
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("repo") == repo and ev.get("pr") == pr:
                rows.append(ev)
            if len(rows) >= 50:
                break
    except OSError:
        return ""
    if not rows:
        return ""
    shown = rows[:EVENTS_LIMIT]
    parts: list[str] = []
    for ev in shown:
        ts = _fmt_ts(ev.get("ts") or "")
        kind = ev.get("kind", "?")
        extras = []
        if "verdict" in ev:
            extras.append(f"verdict={ev['verdict']}")
        if "error_type" in ev:
            extras.append(f"error={ev['error_type']}")
        tail = (" " + ",".join(extras)) if extras else ""
        parts.append(f"{ts} {kind}{tail}")
    extra = len(rows) - EVENTS_LIMIT
    if extra > 0:
        parts.append(f"_+{extra} more_")
    return " · ".join(parts)


def _fmt_ts(iso: str) -> str:
    """ISO 8601 → `5/15 5:30p`. Year is implicit (current). Empty input
    or parse failure returns the raw string trimmed."""
    if not iso:
        return ""
    try:
        t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return iso[:16]
    hour = t.hour % 12 or 12
    suffix = "a" if t.hour < 12 else "p"
    return f"{t.month}/{t.day} {hour}:{t.minute:02d}{suffix}"
