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


@activity.defn
async def ensure_worktree(repo: str, branch: str) -> str:
    """Return an absolute path to a working tree with `branch` checked out.

    Clones if missing. Fetches origin. Checks out `branch`. If the branch
    isn't on the upstream remote (PR from a fork), tries the GitHub
    pull/<pr>/head ref form via `gh pr checkout` if `branch` looks like
    a PR ref. Reset is hard so a previous test_attestation's edits don't
    persist between runs.
    """
    if "/" not in repo:
        raise ApplicationError(f"repo must be owner/repo, got {repo!r}",
                               non_retryable=True)
    if not branch:
        raise ApplicationError("branch required", non_retryable=True)

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
        # Fork case: branch isn't on origin. Fall back to `gh pr checkout`
        # using the PR-state-supplied branch name as the slug to look up.
        gh_co = _run(["gh", "pr", "checkout", branch], cwd=path)
        if gh_co.returncode != 0:
            # Skip rather than halt: the PR likely came from a fork whose
            # branch we can't resolve from name alone (gh needs a PR
            # number for that), or has been deleted. Don't halt the qa
            # line — move on to the next message.
            raise ApplicationError(
                f"skip: cannot check out {repo}@{branch}: "
                f"{(co.stderr or '')[:150]} / {(gh_co.stderr or '')[:150]}",
                non_retryable=True,
            )

    # Pull latest commits on the checked-out branch (no-op if PR ref).
    _run(["git", "pull", "--ff-only", "--quiet"], cwd=path)
    return str(path)
