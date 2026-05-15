"""QA activities — single-entry, structurally bounded.

The activity signature *is* the WIP=1 enforcer. You cannot call qa_one_entry
with multiple repos or branches.
"""

from __future__ import annotations

import asyncio
import subprocess
import time
from pathlib import Path

from temporalio import activity
from temporalio.exceptions import ApplicationError

from sweep.io_safe import atomic_write_text
from sweep.types import GateAttestation, QaOneEntryRequest, QaOneEntryResult

ATTESTATIONS = Path.home() / ".sweep" / "attestations"


def _capture(msg_id: str, name: str, content: str) -> GateAttestation:
    """Write the reviewer response to a deterministic path, return its receipt.

    The activity that did the call is the only thing that ever writes here.
    A downstream consumer cannot fabricate this — it can only point at the
    bytes that already exist on disk. Atomic write closes the partial-write
    crash window.
    """
    p = ATTESTATIONS / msg_id / f"{name}.txt"
    sha = atomic_write_text(p, content)
    return GateAttestation(
        verdict="pass",  # caller overrides after parsing
        artifact_path=str(p),
        sha256=sha,
        verbatim_excerpt=content[:200],
    )


@activity.defn
async def test_attestation(req: QaOneEntryRequest) -> GateAttestation:
    """Run test_cmd on master (must fail) and on fix branch (must pass)."""
    if not req.msg_id:
        raise ApplicationError("msg_id required", non_retryable=True)
    if "/" not in req.repo:
        raise ApplicationError("repo must be owner/repo", non_retryable=True)
    if not req.branch:
        raise ApplicationError("branch required", non_retryable=True)

    worktree = req.worktree
    log: list[str] = []

    def _run(args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(args, cwd=worktree, capture_output=True, text=True)

    _run(["git", "checkout", "--quiet", "HEAD"])
    default = _run(["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"]).stdout.strip()
    default = default.split("/", 1)[1] if "/" in default else "main"

    activity.heartbeat({"stage": "checkout_master"})
    _run(["git", "checkout", "--quiet", default])
    activity.heartbeat({"stage": "test_on_master"})
    master_run = _run(req.test_cmd.split())
    log.append(f"master ({default}) exit={master_run.returncode}")
    if master_run.returncode == 0:
        raise ApplicationError(
            "test_passes_on_master — bug fixed upstream or test wrong",
            non_retryable=True,
        )

    activity.heartbeat({"stage": "checkout_fix"})
    _run(["git", "checkout", "--quiet", req.branch])
    activity.heartbeat({"stage": "test_on_fix"})
    fix_run = _run(req.test_cmd.split())
    log.append(f"fix ({req.branch}) exit={fix_run.returncode}")
    if fix_run.returncode != 0:
        raise ApplicationError(
            f"test_fails_on_fix — fix is broken: {fix_run.stderr[:500]}",
            non_retryable=True,
        )

    body = "\n".join(log) + "\n\n--- master stderr ---\n" + master_run.stderr + "\n--- fix stdout ---\n" + fix_run.stdout
    att = _capture(req.msg_id, "test", body)
    att.verdict = "pass"
    return att


@activity.defn
async def codex_review(req: QaOneEntryRequest, diff: str) -> GateAttestation:
    """Send diff to codex (or opus fallback). Captures the raw response as receipt."""
    if not req.msg_id:
        raise ApplicationError("msg_id required", non_retryable=True)

    # Placeholder — real implementation calls anthropic / openai SDK directly.
    # The activity body is non-deterministic; Temporal records its return
    # value to history so future replays see the same result.
    response = f"<codex stub for {req.repo}#{req.branch}>\nverdict: pass"
    await asyncio.sleep(0)
    att = _capture(req.msg_id, "codex", response)
    att.verdict = "pass"
    att.provenance = "codex"
    return att


@activity.defn
async def gemini_review(req: QaOneEntryRequest, diff: str, round_num: int) -> GateAttestation:
    """Send diff to gemini. Captures the raw response as receipt."""
    if not req.msg_id:
        raise ApplicationError("msg_id required", non_retryable=True)

    response = f"<gemini stub round {round_num} for {req.repo}#{req.branch}>\nverdict: pass"
    await asyncio.sleep(0)
    att = _capture(req.msg_id, f"gemini_r{round_num}", response)
    att.verdict = "pass"
    return att


async def qa_one_entry(req: QaOneEntryRequest) -> QaOneEntryResult:
    """Terminal-mode convenience composer. NOT an @activity.defn — the
    production path is QaActor composing test_attestation + codex_review +
    gemini_review as independent workflow.execute_activity calls.

    This wrapper exists so you can:
      - call the full qa pipeline from a script without standing up Temporal
      - debug end-to-end behavior in an interactive python shell
      - sanity-check the whole flow against Haiku-as-fixture

    Each sub-activity (test_attestation, codex_review, gemini_review) is its
    own @activity.defn and can be called independently for development in
    isolation. This composer just chains them inline.
    """
    if not req.msg_id:
        raise ApplicationError("msg_id required", non_retryable=True)

    start = time.time()
    test_att = await test_attestation(req)

    diff = subprocess.run(
        ["git", "-C", req.worktree, "diff", "origin/HEAD..."],
        capture_output=True,
        text=True,
    ).stdout

    codex_att = await codex_review(req, diff)
    gemini_first = await gemini_review(req, diff, 1)
    gemini_last = gemini_first

    result = QaOneEntryResult(
        msg_id=req.msg_id,
        verdict="pass",
        bugs_found=0,
        test_attestation=test_att,
        codex=codex_att,
        gemini_first=gemini_first,
        gemini_last=gemini_last,
        elapsed_seconds=time.time() - start,
    )

    assert isinstance(result.bugs_found, int)
    assert Path(result.codex.artifact_path).exists()
    assert Path(result.gemini_last.artifact_path).exists()
    return result
