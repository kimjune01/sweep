"""`sweep pr <repo>#<pr>` — per-PR drill-down view.

Same visual register as `sweep floor` and `sweep kanban`: one screen of
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

    # Compute attestation status once. The pivot has three states:
    #   no receipts at all   → absent (locality reads "not yet")
    #   receipts + verdict=pass → ⛩️ attested (through the gate)
    #   receipts + other verdict → 🚧 failing (blocked at the gate)
    msg_ids = _msg_ids_for(repo, pr)
    artifacts = _artifacts_for(msg_ids)
    verdict = _latest_qa_verdict(repo, pr) if artifacts else None

    print(f"# {repo}#{pr} — {title}")
    print()
    print(f"<{url}>  _| `gh pr view {repo} {pr}`_")
    print()

    _render_hypothesis(repo)
    _render_attest(artifacts=bool(artifacts), verdict=verdict)
    _render_remote(data)
    _render_origin(repo, data)
    _render_receipts(msg_ids, artifacts)
    _render_events(repo, pr)


# ---------------------------------------------------------------- sections


def _hypothesis_path(repo: str) -> Path:
    slug = repo.replace("/", "-")
    return REPOS_DIR / f"{slug}.md"


def _render_hypothesis(repo: str) -> None:
    """Terse bullets pulled from the maintainer-preferences section of the
    repo's hypothesis file. Hidden when the file doesn't exist."""
    path = _hypothesis_path(repo)
    if not path.exists():
        return
    bullets = _extract_bullets(path)
    if not bullets:
        return
    print("---")
    print()
    for b in bullets[:HYPOTHESIS_BULLETS]:
        print(f"- {b}")
    extra = len(bullets) - HYPOTHESIS_BULLETS
    if extra > 0:
        print(f"- _… +{extra} more_")
    print(f"_| `cat {path}`_")
    print()
    print("---")
    print()


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


def _render_attest(*, artifacts: bool, verdict: str | None) -> None:
    """Local stats — attestation pivot. The PR is either ⛩️ Attested
    (cascade ran and the verdict is pass) or 🚧 Unattested (anything
    else: cascade hasn't run, is in flight, or returned a non-pass
    verdict). Always rendered because the pivot is binary and load-
    bearing — it determines whether sweep ships the PR.

    Local properties only — what sweep knows from its own substrate.
    Kept on a separate line from the remote stats below because
    mixing local and remote facts confuses the operator about which
    half of the system to interrogate when something's wrong."""
    if artifacts and verdict == "pass":
        glyph = "⛩️ Attested"
    else:
        glyph = "🚧 Unattested"
    print(f"`{glyph}`")
    print()


def _render_remote(data: dict) -> None:
    """Remote stats — what GitHub knows about the PR. CI, review,
    mergeable, draft, stale. Distinct line from the local attestation
    state above so the operator can tell at a glance whether a problem
    is sweep-side (no receipts / failing cascade) or GitHub-side (CI
    red / review changes requested / merge conflict)."""
    ci_key = _ci_status(data.get("statusCheckRollup") or [])
    review = data.get("reviewDecision") or ""
    merge = data.get("mergeable") or ""

    cells = [f"{CI_GLYPHS.get(ci_key, '·')} {ci_key}"]
    if review:
        cells.append(REVIEW_GLYPHS.get(review, f"· {review}"))
    if merge:
        cells.append(MERGE_GLYPHS.get(merge, f"· {merge}"))
    if data.get("isDraft"):
        cells.append("📝 draft")
    cells.append(_stale(data.get("updatedAt", "")))
    print(f"`{' · '.join(cells)}`")
    print()


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


def _render_origin(repo: str, data: dict) -> None:
    """Origin pointers — issue references in PR body + hypothesis file path.
    No header — these are pointer-shaped lines, distinct from the stats
    line above and the bullet lists below."""
    body = data.get("body") or ""
    refs = sorted(set(int(n) for n in REF_RE.findall(body)))
    hypo = _hypothesis_path(repo)

    if not refs and not hypo.exists():
        return

    if refs:
        first = refs[0]
        url = f"https://github.com/{repo}/issues/{first}"
        more = f" (+{len(refs)-1} more)" if len(refs) > 1 else ""
        print(f"issue #{first}{more} — `gh issue view {repo} {first}` · <{url}>")
    if hypo.exists():
        print(f"hypothesis — `cat {hypo}`")
    print()


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


def _render_receipts(msg_ids: list[str], artifacts: list[tuple[str, Path]]) -> None:
    if not artifacts:
        return
    total = len(artifacts)
    shown = artifacts[:RECEIPTS_LIMIT]
    # No header — locality names these: after origin pointers, before
    # events. The `filename` + msg_id shape distinguishes from the
    # timestamp-leading event lines below.
    for msg_id, p in shown:
        print(f"`{p.name}` _msg_id `{msg_id}`_")
    if total > RECEIPTS_LIMIT:
        print(f"_… +{total - RECEIPTS_LIMIT} more · `sweep attest for-msg {msg_ids[0]}`_")
    print()


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


def _render_events(repo: str, pr: int) -> None:
    rows: list[dict] = []
    if not observe.EVENTS.exists():
        return
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
        return
    if not rows:
        return
    shown = rows[:EVENTS_LIMIT]
    # No header — the timestamp-leading shape names these as events;
    # locality (last section, after receipts) reinforces.
    for ev in shown:
        ts = (ev.get("ts") or "")[:16]
        kind = ev.get("kind", "?")
        extras = []
        if "verdict" in ev:
            extras.append(f"verdict={ev['verdict']}")
        if "rounds" in ev:
            extras.append(f"rounds={ev['rounds']}")
        if "error_type" in ev:
            extras.append(f"error={ev['error_type']}")
        tail = " · ".join(extras)
        print(f"`{ts}` `{kind}`{(' · ' + tail) if tail else ''}")
    if len(rows) > EVENTS_LIMIT:
        print(f"_… +{len(rows) - EVENTS_LIMIT} more · `sweep observe events --limit 50`_")
    print()
