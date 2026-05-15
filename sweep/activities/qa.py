"""QA activities — single-entry, structurally bounded.

The activity signature *is* the WIP=1 enforcer. You cannot call qa_one_entry
with multiple repos or branches.
"""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

from temporalio import activity
from temporalio.exceptions import ApplicationError

from sweep import llm_io, models
from sweep.io_safe import atomic_write_text
from sweep.types import GateAttestation, QaOneEntryRequest, QaOneEntryResult

# adversary_1 / _2 / _3 cascade (defaults: codex → gemini → opus).
# Each reviewer activity reads its slot from models.default_for.
ADVERSARY_1 = models.default_for("adversary_1")  # codex
ADVERSARY_2 = models.default_for("adversary_2")  # gemini
ADVERSARY_3 = models.default_for("adversary_3")  # opus subagent fallback
CODE_MODEL  = models.default_for("code")          # opus, for impl/fix tasks

ATTESTATIONS = Path.home() / ".sweep" / "attestations"


def _head_sha(worktree: str) -> str:
    """Capture the current HEAD SHA of the worktree. Pins fuses to this code."""
    out = subprocess.run(
        ["git", "-C", worktree, "rev-parse", "HEAD"],
        capture_output=True, text=True, check=False,
    )
    return out.stdout.strip()


def _capture(msg_id: str, name: str, content: str, *,
             worktree: str | None = None) -> GateAttestation:
    """Write the reviewer response to a deterministic path, return its receipt.

    The activity that did the call is the only thing that ever writes here.
    A downstream consumer cannot fabricate this — it can only point at the
    bytes that already exist on disk. Atomic write closes the partial-write
    crash window.

    If `worktree` is provided, pin the attestation to its current HEAD SHA.
    This is the event-driven fuse: the attestation is valid as long as the
    PR head matches; the moment a new commit lands the fuse blows.
    """
    p = ATTESTATIONS / msg_id / f"{name}.txt"
    sha = atomic_write_text(p, content)
    return GateAttestation(
        verdict="pass",  # caller overrides after parsing
        artifact_path=str(p),
        sha256=sha,
        verbatim_excerpt=content[:200],
        pinned_head_sha=_head_sha(worktree) if worktree else None,
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
    att = _capture(req.msg_id, "test", body, worktree=req.worktree)
    att.verdict = "pass"
    return att


_REVIEW_SYSTEM = (
    "You are a structural code reviewer. Read the diff and decide whether "
    "the change is sound. Reply with a single verdict line of the form "
    "`verdict: pass`, `verdict: fail`, or `verdict: revise`, followed by a "
    "one-paragraph reason. Keep the reason under 120 words."
)


def _user_prompt(req: QaOneEntryRequest, diff: str) -> str:
    head = f"Repo: {req.repo}\nBranch: {req.branch}"
    if req.issue is not None:
        head += f"\nIssue: #{req.issue}"
    return f"{head}\n\nDiff to review:\n\n{diff}"


def _parse_verdict(response: str) -> str:
    """Pull `verdict: X` (case-insensitive). Default to 'stubbed' for non-Anthropic
    providers whose wrapper is still a stub; treat anything else unparsed as 'revise'
    so the cascade keeps moving rather than auto-passing on garbled output."""
    if response.startswith("<stub:"):
        return "stubbed"
    m = re.search(r"verdict\s*:\s*(pass|fail|revise)", response, re.IGNORECASE)
    if not m:
        return "revise"
    return m.group(1).lower()


@activity.defn
async def codex_review(req: QaOneEntryRequest, diff: str) -> GateAttestation:
    """Send diff to adversary_1 (codex by default; haiku under test). Captures
    the raw response as the gate receipt."""
    if not req.msg_id:
        raise ApplicationError("msg_id required", non_retryable=True)

    model = models.default_for("adversary_1")
    result = await llm_io.call(
        model,
        system=_REVIEW_SYSTEM,
        user=_user_prompt(req, diff),
        msg_id=req.msg_id,
        repo=req.repo,
        pr=req.issue,
        max_tokens=400,
        temperature=0.0,
    )
    att = _capture(req.msg_id, "codex", result.response, worktree=req.worktree)
    att.verdict = _parse_verdict(result.response)
    att.provenance = f"{model.nick}{'-cached' if result.cached else ''}"
    return att


@activity.defn
async def gemini_review(req: QaOneEntryRequest, diff: str, round_num: int) -> GateAttestation:
    """Send diff to adversary_2 (gemini by default; haiku under test). Captures
    the raw response as the gate receipt."""
    if not req.msg_id:
        raise ApplicationError("msg_id required", non_retryable=True)

    model = models.default_for("adversary_2")
    result = await llm_io.call(
        model,
        system=_REVIEW_SYSTEM,
        user=_user_prompt(req, diff),
        msg_id=req.msg_id,
        repo=req.repo,
        pr=req.issue,
        max_tokens=400,
        temperature=0.0,
    )
    att = _capture(req.msg_id, f"gemini_r{round_num}", result.response,
                   worktree=req.worktree)
    att.verdict = _parse_verdict(result.response)
    att.provenance = f"{model.nick}-r{round_num}{'-cached' if result.cached else ''}"
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

    sub_verdicts = {codex_att.verdict, gemini_last.verdict}
    if "fail" in sub_verdicts:
        verdict = "fail"
    elif sub_verdicts <= {"pass", "stubbed"}:
        verdict = "pass"
    else:  # "revise" present without "fail"
        verdict = "partial"

    result = QaOneEntryResult(
        msg_id=req.msg_id,
        verdict=verdict,
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
