"""`sweep evict` — process the sink for PRs needing draft+apology.

Bridges the gap between `attest_routed verdict=skip target=sink` and
the maintainer-side action (draft the PR, post an honest apology
comment). Without this the operator does it by hand per PR.

Reasons we know how to apologize for:
  no_tests_in_pr         — PR ships without tests; can't attest
  Windows-only           — host can't reproduce
  Zig hash mismatch      — toolchain version pinning needed
  test_passes_on_master  — bug appears fixed upstream
  generic                — fallback honest "can't validate on current setup"

Idempotent: skips PRs already drafted (re-running is safe).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import typer

evict_app = typer.Typer(
    help="Process sink for PRs needing draft+apology.",
    no_args_is_help=True,
)

SINK = Path.home() / ".sweep" / "inbox" / "sink.jsonl"


# Reason-class → apology template. Match by `in` (substring). Order
# matters — more specific first. Each template is the apology body
# only; the actor wraps with "Human here. ..." consistency.
_REASON_TEMPLATES: list[tuple[str, str]] = [
    ("no_tests_in_pr",        "PR lacks a test exercising the change, so drafting. Please close or take it over."),
    ("Windows-only",           "Cannot validate on macOS (Windows-only fix), so drafting. Please close or take it over."),
    ("Zig version",            "Local Zig version cannot build the lockfile, so drafting. Please close or take it over."),
    ("test_passes_on_master",  "Test passes on master too; appears already fixed. Closing."),
    ("host_compat",            "Test environment unreachable from this host, so drafting. Please close or take it over."),
]


def _apology_for(reason: str) -> str:
    body = "Cannot validate on current setup, so drafting. Please close or take it over."
    for needle, template in _REASON_TEMPLATES:
        if needle in reason:
            body = template
            break
    return body


# Sink reasons that mean "good outcome, don't touch the PR." The
# evictor MUST skip these — drafting an approved PR is the worst
# possible action. Substring match; case-insensitive.
_DO_NOT_EVICT_REASONS = (
    "approved",
    "merged",
    "maintainers court",
    "maintainer's court",
    "ready to ship",
)


def _is_do_not_evict(reason: str) -> bool:
    r = (reason or "").lower()
    return any(needle in r for needle in _DO_NOT_EVICT_REASONS)


def _gh_pr_state(repo: str, pr: int) -> dict | None:
    """Return current PR JSON or None on failure."""
    r = subprocess.run(
        ["gh", "pr", "view", str(pr), "--repo", repo, "--json",
         "isDraft,state,title,reviewDecision"],
        capture_output=True, text=True, timeout=20,
    )
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def _draft_and_comment(repo: str, pr: int, apology: str) -> tuple[bool, str]:
    """Convert to draft + post apology. Returns (ok, message)."""
    d = subprocess.run(
        ["gh", "pr", "ready", "--undo", str(pr), "--repo", repo],
        capture_output=True, text=True, timeout=30,
    )
    if d.returncode != 0:
        return False, f"draft failed (rc={d.returncode}): {(d.stderr or '')[:200]}"
    c = subprocess.run(
        ["gh", "pr", "comment", str(pr), "--repo", repo, "--body", apology],
        capture_output=True, text=True, timeout=30,
    )
    if c.returncode != 0:
        return False, f"comment failed (rc={c.returncode}): {(c.stderr or '')[:200]}"
    return True, c.stdout.strip().split("\n")[-1]


def _close_with_comment(repo: str, pr: int, comment: str) -> tuple[bool, str]:
    """Close the PR with one explanatory comment. Used for cases where
    we have authoritative grounds to close ourselves (e.g.,
    test_passes_on_master means the bug is already fixed upstream —
    no maintainer decision needed). `gh pr close --comment` does both
    in a single atomic step."""
    r = subprocess.run(
        ["gh", "pr", "close", str(pr), "--repo", repo, "--comment", comment],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        return False, f"close failed (rc={r.returncode}): {(r.stderr or '')[:200]}"
    return True, r.stdout.strip().split("\n")[-1] if r.stdout.strip() else "closed"


# Reasons we close ourselves (no maintainer decision needed). Substring
# match. Add to this set when the substrate has authoritative grounds
# to take terminal action on its own.
_SELF_CLOSE_REASONS = ("test_passes_on_master",)


def _should_self_close(reason: str) -> bool:
    r = (reason or "").lower()
    return any(needle.lower() in r for needle in _SELF_CLOSE_REASONS)


def _read_sink() -> list[dict]:
    if not SINK.exists():
        return []
    out: list[dict] = []
    for line in SINK.read_text().splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


@evict_app.command("process-sink")
def evict_process_sink(
    dry: bool = typer.Option(False, "--dry", help="Print what would be done, don't touch GitHub"),
    only_repo: str = typer.Option(None, "--repo", help="Restrict to one repo"),
) -> None:
    """Walk sink.jsonl, draft+apology for PRs not yet drafted whose
    reason matches a known unattestable class. Idempotent — skips PRs
    already in draft.

    Pulls (repo, pr, reason) from each sink row, queries gh for current
    state, posts apology + drafts if open. Logs each decision.
    """
    rows = _read_sink()
    # Latest reason per (repo, pr).
    latest: dict[tuple[str, int], dict] = {}
    for r in rows:
        repo = r.get("repo")
        pr = r.get("pr")
        if not repo or not pr:
            continue
        if only_repo and repo != only_repo:
            continue
        latest[(repo, int(pr))] = r

    if not latest:
        print(f"(no sink entries{' for ' + only_repo if only_repo else ''})")
        return

    drafted = 0
    closed = 0
    skipped = 0
    failed = 0
    for (repo, pr), r in sorted(latest.items()):
        reason = r.get("reason", "?")
        # Safety: never draft a PR whose sink reason was a GOOD outcome.
        # Approved / merged / "maintainer's court" rows are in the sink
        # because they're done, not because they need apology.
        if _is_do_not_evict(reason):
            print(f"  ⊘ {repo}#{pr}: do-not-evict reason ({reason[:60]!r})")
            skipped += 1
            continue
        state = _gh_pr_state(repo, pr)
        if state is None:
            print(f"  ? {repo}#{pr}: gh fetch failed, skipping")
            skipped += 1
            continue
        if state.get("state") != "OPEN":
            print(f"  · {repo}#{pr}: state={state.get('state')}, no action")
            skipped += 1
            continue
        # Secondary safety: query gh for reviewDecision; if it's
        # APPROVED, refuse any terminal action regardless of sink reason.
        rdec = (state.get("reviewDecision") or "")
        if rdec == "APPROVED":
            print(f"  ⊘ {repo}#{pr}: live gh state shows APPROVED, refusing action")
            skipped += 1
            continue
        comment = _apology_for(reason)

        # Two routes:
        #   self-close (e.g. test_passes_on_master) — substrate has
        #     authoritative grounds; close ourselves, no maintainer
        #     decision needed
        #   draft+comment (everything else) — surface to maintainer
        #     with explicit close-or-take-it-over ask
        if _should_self_close(reason):
            if dry:
                print(f"  would-close: {repo}#{pr}  reason={reason[:60]!r}")
                print(f"               comment: {comment[:100]}")
                continue
            ok, msg = _close_with_comment(repo, pr, comment)
            if ok:
                print(f"  ✓ {repo}#{pr}: closed + commented  {msg}")
                closed += 1
            else:
                print(f"  ✗ {repo}#{pr}: {msg}")
                failed += 1
            continue

        # Draft path: skip if already drafted (idempotent).
        if state.get("isDraft"):
            print(f"  · {repo}#{pr}: already draft, no action")
            skipped += 1
            continue
        if dry:
            print(f"  would-draft: {repo}#{pr}  reason={reason[:60]!r}")
            print(f"               comment: {comment[:100]}")
            continue
        ok, msg = _draft_and_comment(repo, pr, comment)
        if ok:
            print(f"  ✓ {repo}#{pr}: drafted + commented  {msg}")
            drafted += 1
        else:
            print(f"  ✗ {repo}#{pr}: {msg}")
            failed += 1

    print(f"\n{drafted} drafted, {closed} closed, {skipped} skipped, {failed} failed")


_INBOX_DIR = Path.home() / ".sweep" / "inbox"


@evict_app.command("flush")
def evict_flush(
    repo: str = typer.Option(..., help="owner/repo to flush from all actor inboxes"),
    dry: bool = typer.Option(False, "--dry", help="Print what would be removed"),
) -> None:
    """Walk every actor inbox jsonl and remove rows for the given
    repo. Run after marking a repo evicted to flush any in-flight
    cards. The activity-entry short-circuit (`is_repo_evicted`) is the
    real guarantee — this is cleanup so the inbox files don't carry
    permanent residue."""
    if not _INBOX_DIR.exists():
        print(f"(no inbox dir at {_INBOX_DIR})")
        return
    total_removed = 0
    for inbox in sorted(_INBOX_DIR.glob("*.jsonl")):
        kept: list[str] = []
        removed = 0
        for line in inbox.read_text().splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                kept.append(line)
                continue
            if row.get("repo") == repo:
                removed += 1
                continue
            kept.append(line)
        if removed == 0:
            continue
        if dry:
            print(f"  would-remove {removed:3d} from {inbox.name}")
        else:
            inbox.write_text("\n".join(kept) + ("\n" if kept else ""))
            print(f"  removed {removed:3d} from {inbox.name}")
        total_removed += removed
    print(f"\ntotal: {total_removed} card(s) flushed for {repo}")
