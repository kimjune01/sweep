"""Worktree manager — given (repo, branch), return a checked-out path.

Clones into ~/.sweep/worktrees/<owner>__<repo>/ on first use, then for
each call fetches origin and checks out the requested branch (or the
PR ref if the branch lives on a fork). Idempotent: re-running with the
same (repo, branch) updates in-place.

QaActor calls this before every test_attestation so the activity gets
a real cwd instead of `""`. Failures here surface as non-retryable
ApplicationError so the actor's andon cord catches them.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

from temporalio import activity
from temporalio.exceptions import ApplicationError


WORKTREE_ROOT = Path.home() / ".sweep" / "worktrees"


def _safe_dir(repo: str) -> Path:
    return WORKTREE_ROOT / repo.replace("/", "__")


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Subprocess wrapper that converts FileNotFoundError (missing binary,
    empty cwd) into a non-retryable ApplicationError. Without this, the
    actor sees a generic OSError, treats it as retryable, and loops."""
    try:
        return subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    except FileNotFoundError as e:
        raise ApplicationError(
            f"subprocess setup failed: {e}; args={args!r} cwd={cwd!r}",
            non_retryable=True,
        )


@activity.defn
async def mark_started(msg_id: str) -> None:
    """Append a start record for the cockpit's in-flight view. Without
    this, view-layer in-flight is always 0 because nothing else writes
    to _started.jsonl. Idempotent: cockpit dedupes by msg_id."""
    from sweep.inbox_state import INBOX_DIR
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    path = INBOX_DIR / "_started.jsonl"
    import json
    with open(path, "a") as f:
        f.write(json.dumps({"msg_id": msg_id}) + "\n")


@activity.defn
async def mark_acked(msg_id: str) -> None:
    """Append an ack record so the message leaves the cockpit's queued/
    in-flight counts. Idempotent at the cockpit layer (set semantics)."""
    from sweep.inbox_state import INBOX_DIR
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    path = INBOX_DIR / "_acks.jsonl"
    import json
    with open(path, "a") as f:
        f.write(json.dumps({"msg_id": msg_id}) + "\n")


# Andon markers — one file per halted actor. Cockpit lists this dir to
# decide whether to flash the 🚨 banner. File contents are the receipt
# (what halted, why, when). Deleted on clear_andon signal.
ANDON_DIR = Path.home() / ".sweep" / "control" / "andon"


@activity.defn
async def record_andon(actor: str, msg_id: str, reason: str) -> None:
    """Write a marker file when an actor halts. Cockpit reads the dir to
    show a red banner. One file per actor (replaces any prior marker for
    the same actor, since the actor only halts once at a time).

    Also pauses the line — andon is "something broke," which by
    definition means the line should not be producing more work until
    the operator looks. The pause clears in `clear_andon_marker` once
    the last andon marker is removed.
    """
    import datetime as _dt
    import json
    from sweep.control_state import set_paused
    ANDON_DIR.mkdir(parents=True, exist_ok=True)
    path = ANDON_DIR / f"{actor}.json"
    payload = {
        "actor": actor,
        "msg_id": msg_id,
        "reason": reason[:500],
        "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload))
    set_paused(True)
    # Observability: stoppage starts now. The wasteboard pairs this
    # with `andon_cleared` to compute downtime per window. Without
    # the event, stoppage is invisible to the longitudinal view.
    from sweep import observe
    observe.event("andon_recorded", actor=actor, msg_id=msg_id,
                  reason=reason[:200], ts=payload["ts"])


@activity.defn
async def clear_andon_marker(actor: str) -> None:
    """Remove the marker file when an actor's andon is cleared. No-op if
    the file doesn't exist (clearing an unhalted actor is fine).

    When this clear leaves no markers behind, lift the pause that
    `record_andon` set — the operator clearing the last error is the
    "ready to run" signal. Independent andons on other actors keep the
    line paused until they're all cleared.
    """
    from sweep.control_state import set_paused
    from sweep import observe
    path = ANDON_DIR / f"{actor}.json"
    cleared = False
    try:
        path.unlink()
        cleared = True
    except FileNotFoundError:
        pass
    if not any(ANDON_DIR.glob("*.json")):
        set_paused(False)
    if cleared:
        observe.event("andon_cleared", actor=actor)


def _ensure_worktree_blocking(repo: str, branch: str, pr: int | None = None) -> str:
    """Synchronous body of ensure_worktree. Six git/gh subprocesses end-
    to-end (up to ~minute on cold clone, 5–15s warm) — run via
    asyncio.to_thread so the worker's event loop doesn't stall on git I/O."""
    WORKTREE_ROOT.mkdir(parents=True, exist_ok=True)
    path = _safe_dir(repo)

    if not (path / ".git").exists():
        clone = _run(["git", "clone", "--quiet",
                      f"https://github.com/{repo}.git", str(path)])
        if clone.returncode != 0:
            raise ApplicationError(
                f"git clone {repo} failed: {(clone.stderr or '')[:300]}",
                non_retryable=True,
            )

    # Discard any local edits before fetching/checking out.
    _run(["git", "reset", "--hard", "--quiet"], cwd=path)
    _run(["git", "clean", "-fdq"], cwd=path)

    fetch = _run(["git", "fetch", "--quiet", "origin"], cwd=path)
    if fetch.returncode != 0:
        raise ApplicationError(
            f"git fetch origin failed: {(fetch.stderr or '')[:300]}",
            non_retryable=True,
        )

    co = _run(["git", "checkout", "--quiet", branch], cwd=path)
    if co.returncode != 0:
        # Fork case: branch isn't on origin. Fall back to `gh pr checkout`.
        # Prefer the PR number when caller supplied one — unambiguous for
        # fork PRs (gh fetches refs/pull/<n>/head). Branch-name form only
        # matches PRs whose head is on the upstream remote, which is
        # exactly the case `git checkout` already covers; for fork PRs it
        # 404s with "no pull requests found for branch ...".
        gh_target = str(pr) if pr else branch
        gh_co = _run(["gh", "pr", "checkout", gh_target], cwd=path)
        if gh_co.returncode != 0:
            raise ApplicationError(
                f"skip: cannot check out {repo}@{branch} "
                f"(gh pr checkout {gh_target}): "
                f"{(co.stderr or '')[:150]} / {(gh_co.stderr or '')[:150]}",
                non_retryable=True,
            )

    # Pull latest commits on the checked-out branch (no-op if PR ref).
    _run(["git", "pull", "--ff-only", "--quiet"], cwd=path)
    return str(path)


def _git_remote_url(path: Path) -> str | None:
    """Return remote.origin.url for a git dir, or None if not a clean
    git checkout. Used as a safety check before rm-ing a directory
    that could plausibly contain user data."""
    if not (path / ".git").exists():
        return None
    try:
        out = subprocess.run(
            ["git", "-C", str(path), "config", "--get", "remote.origin.url"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode != 0:
            return None
        return out.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def _matches_repo(url: str, repo: str) -> bool:
    """Loose match: github URL contains owner/repo (handles https://,
    git@, .git suffix variants)."""
    if not url or not repo:
        return False
    needle = repo.lower()
    hay = url.lower().removesuffix(".git")
    return needle in hay


def prune_evicted_worktree(repo: str) -> dict:
    """Remove the substrate's worktree for an evicted repo AND any
    matching ~/Documents/ ad-hoc clone, if the clone's origin URL
    actually matches `repo` (so we never wipe an unrelated dir that
    happens to share a name).

    Returns a dict listing what was removed, what was skipped, and why
    — leakdog/cockpit can surface this when curiosity wins."""
    import shutil

    removed: list[str] = []
    skipped: list[str] = []

    # 1. Substrate worktree — we own this dir unconditionally, so no
    # remote-URL safety check is required (the path itself encodes the
    # repo via _safe_dir's owner__repo convention).
    wt = _safe_dir(repo)
    if wt.exists():
        try:
            shutil.rmtree(wt)
            removed.append(str(wt))
        except OSError as e:
            skipped.append(f"{wt}: {e}")

    # 1b. Build cache — sibling of the worktree under ~/.sweep/build-cache/.
    # Same naming convention (`_safe_dir`'s owner__repo). Wiping it on
    # repo eviction reclaims disk for the actively-attested set.
    bc = Path.home() / ".sweep" / "build-cache" / wt.name
    if bc.exists():
        try:
            shutil.rmtree(bc)
            removed.append(str(bc))
        except OSError as e:
            skipped.append(f"{bc}: {e}")

    # 2. Ad-hoc Documents/ clones. Operator may have cloned the repo
    # under one of several naming conventions; check all the plausible
    # ones but only remove dirs whose remote actually matches.
    docs = Path.home() / "Documents"
    slug_short = repo.split("/")[-1]
    slug_dash = repo.replace("/", "-")
    slug_under = repo.replace("/", "__")
    candidates = {docs / slug_short, docs / slug_dash, docs / slug_under,
                  docs / f"{slug_short}-investigate",
                  docs / f"{slug_dash}-investigate"}
    for cand in candidates:
        if not cand.exists() or not cand.is_dir():
            continue
        url = _git_remote_url(cand)
        if not _matches_repo(url or "", repo):
            skipped.append(f"{cand}: remote {url!r} does not match {repo}")
            continue
        try:
            shutil.rmtree(cand)
            removed.append(str(cand))
        except OSError as e:
            skipped.append(f"{cand}: {e}")

    return {"repo": repo, "removed": removed, "skipped": skipped}


@activity.defn
async def ensure_worktree(repo: str, branch: str, pr: int | None = None) -> str:
    """Return an absolute path to a working tree with `branch` checked out.

    Clones if missing. Fetches origin. Checks out `branch`. If the branch
    isn't on the upstream remote (PR from a fork), tries the GitHub
    pull/<pr>/head ref form via `gh pr checkout`. Pass `pr` whenever the
    caller knows it — the PR-number form of `gh pr checkout` works for
    fork branches, the branch-name form does not. Reset is hard so a
    previous test_attestation's edits don't persist between runs.
    """
    if "/" not in repo:
        raise ApplicationError(f"repo must be owner/repo, got {repo!r}",
                               non_retryable=True)
    if not branch:
        raise ApplicationError("branch required", non_retryable=True)
    return await asyncio.to_thread(_ensure_worktree_blocking, repo, branch, pr)
