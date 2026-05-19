"""QaActor — one long-running workflow that owns the qa inbox.

Receives messages via signal. Processes one at a time (WIP=1 enforced by the
activity signature). Tracks andon state via a `halted` flag that the workflow
exposes through a query handler.

In normal operation this workflow never completes — it's a persistent actor.
The supervisor (or a human) can `temporal workflow terminate` it for hard
reset.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError


# Concurrency cap — how many messages may be in flight at once. Matches
# CAPS['qa']['in_flight'] in cockpit.py. WIP=1 was an artefact of the
# earlier serial loop; the view layer already shows 5/5 so the actor
# should match.
MAX_IN_FLIGHT = 5

# Pull-shaped backpressure on the qa→attest interface. qa dispatches
# faster than attest can drain (multi-LLM review ≈ 2-3 min/card; full
# test_attestation ≈ 1-15 min/card). Without this ceiling, qa pulls
# from its inbox and stuffs attest.jsonl unboundedly. With it, qa
# blocks before pulling once attest's pending queue hits the ceiling,
# letting the bottleneck regulate the rest of the line.
# 3 = (1 in-flight in attest + up to 2 buffered). Small enough to keep
# attest from sitting idle on transient stalls, low enough that a
# permanently-stuck attest can't snowball.
ATTEST_PENDING_CEILING = 3

def _skip_marker(e: BaseException) -> str | None:
    """Return the skip-message string if any link in e's cause chain is
    an ApplicationError whose message starts with 'skip:'. None means
    'this is a real failure, halt the actor'."""
    seen: set[int] = set()
    cur = e
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        m = getattr(cur, "message", None)
        if isinstance(m, str) and m.startswith("skip:"):
            return m
        cur = getattr(cur, "cause", None) or cur.__cause__


with workflow.unsafe.imports_passed_through():
    from pathlib import Path
    from sweep.activities.infer import infer_test_cmd
    from sweep.activities.qa import (
        codex_review,
        extract_qa_verdicts,
        gemini_review,
        read_artifact_texts,
    )
    from sweep.activities.synth_test import synth_test_for_fix
    from sweep.activities.attest import attest_pending_depth, kick_attest_card
    from sweep.activities.pause_gate import should_idle
    from sweep.activities.rope import kick_rope_card
    from sweep.activities.worktree import (
        clear_andon_marker,
        ensure_worktree,
        mark_acked,
        mark_started,
        record_andon,
    )
    from sweep.types import Message, QaOneEntryRequest, QaOneEntryResult


@workflow.defn
class QaActor:
    def __init__(self) -> None:
        self._pending: list[Message] = []
        self._seen_msg_ids: set[str] = set()
        self.halted: bool = False
        self.in_flight: int = 0
        self.last_outcome: QaOneEntryResult | None = None

    @workflow.signal
    async def deliver(self, msg: Message) -> None:
        """Idempotent inbox. Re-delivery of the same msg_id is a no-op."""
        if msg.msg_id in self._seen_msg_ids:
            return
        self._seen_msg_ids.add(msg.msg_id)
        self._pending.append(msg)

    @workflow.signal
    async def clear_andon(self) -> None:
        self.halted = False
        await workflow.execute_activity(
            clear_andon_marker, args=["qa"],
            start_to_close_timeout=timedelta(seconds=5),
        )

    @workflow.query
    def depth(self) -> int:
        return len(self._pending)

    @workflow.query
    def state(self) -> dict:
        return {
            "depth": len(self._pending),
            "halted": self.halted,
            "seen_total": len(self._seen_msg_ids),
            "in_flight": self.in_flight,
        }

    @workflow.run
    async def run(self) -> None:
        # Dispatcher loop: dequeue when there's pending work AND we're
        # under the concurrency cap AND not halted. Each dispatched
        # message runs in its own task; failures bookkeep via in_flight
        # decrement in `_process_one`'s finally.
        while True:
            await workflow.wait_condition(lambda: (
                self._pending and self.in_flight < MAX_IN_FLIGHT and not self.halted
            ))
            # Inbox-boundary pause check: idle while paused or while
            # qa's own budget andon is held. In-flight tasks finish.
            while await workflow.execute_activity(
                should_idle, args=["qa"],
                start_to_close_timeout=timedelta(seconds=5),
                retry_policy=RetryPolicy(maximum_attempts=2),
            ):
                await workflow.sleep(timedelta(seconds=10))
            # Pull-shaped backpressure on the qa→attest interface.
            # Don't dispatch when attest is saturated; let the
            # bottleneck regulate. Same kanban primitive as rope→roll.
            while await workflow.execute_activity(
                attest_pending_depth,
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=RetryPolicy(maximum_attempts=2),
            ) >= ATTEST_PENDING_CEILING:
                await workflow.sleep(timedelta(seconds=10))
            msg = self._pending.pop(0)
            self.in_flight += 1
            asyncio.create_task(self._process_one(msg))

    async def _process_one(self, msg: Message) -> None:
        # Short-circuit cards for evicted repos. Same activity-entry
        # guarantee attest_cycle uses; catches any in-flight cards
        # that landed before the operator marked the repo evicted.
        try:
            evicted = await workflow.execute_activity(
                "is_repo_evicted_activity", args=[msg.repo],
                start_to_close_timeout=timedelta(seconds=5),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
            if evicted:
                workflow.logger.info(
                    "evicted_skip: msg_id=%s repo=%s", msg.msg_id, msg.repo,
                )
                await workflow.execute_activity(
                    mark_acked, args=[msg.msg_id],
                    start_to_close_timeout=timedelta(seconds=5),
                )
                return
        except Exception:
            # Best-effort short-circuit; fall through to normal
            # processing if the check itself errors.
            pass

        try:
            req = QaOneEntryRequest(
                msg_id=msg.msg_id,
                repo=msg.repo,
                branch=msg.branch or "",
                worktree=msg.payload.get("worktree", ""),
                test_cmd=msg.payload.get("test_cmd", ""),
                issue=msg.pr,
            )

            # Mark in-flight at the view layer the moment we dequeue,
            # before any work. Without this, cockpit shows 0 in-flight
            # even when the actor is mid-task.
            await workflow.execute_activity(
                mark_started, args=[msg.msg_id],
                start_to_close_timeout=timedelta(seconds=5),
            )
            try:
                # Worktree first. Honor an operator-supplied worktree
                # on the payload (same shape as attest_cycle): useful
                # when the fix branch lives on a fork the substrate's
                # upstream clone can't reach. Otherwise ensure_worktree
                # clones/fetches and self-heals across machine moves.
                if req.worktree and Path(req.worktree).is_dir():
                    worktree_path = req.worktree
                else:
                    worktree_path = await workflow.execute_activity(
                        ensure_worktree,
                        args=[req.repo, req.branch, req.issue],
                        # 10 min ceiling: large monorepos (chisel ~1.7GB,
                        # servo ~2.9GB, grafana ~3.7GB) routinely take
                        # 5-8 min for cold-clone over residential
                        # network. 3min was the original optimistic
                        # value; chisel#5311's timeout was the witness.
                        start_to_close_timeout=timedelta(minutes=10),
                        retry_policy=RetryPolicy(
                            maximum_attempts=2,
                            non_retryable_error_types=["ApplicationError"],
                        ),
                    )
                # Test command: routed messages have an empty test_cmd
                # because remit has no idea what the repo's convention
                # is. infer_test_cmd asks the orchestrate LLM, then caches
                # in retro_params so future cycles for the same repo skip
                # the round-trip.
                test_cmd = req.test_cmd
                if not test_cmd:
                    test_cmd = await workflow.execute_activity(
                        infer_test_cmd,
                        args=[worktree_path, req.repo],
                        start_to_close_timeout=timedelta(minutes=2),
                        retry_policy=RetryPolicy(
                            maximum_attempts=2,
                            non_retryable_error_types=["ApplicationError"],
                        ),
                    )
                req = QaOneEntryRequest(
                    msg_id=req.msg_id, repo=req.repo, branch=req.branch,
                    worktree=worktree_path, test_cmd=test_cmd,
                    issue=req.issue,
                )

                # synth_test — if the fix lacks a regression test, ask
                # the synth agent to write one against the unfixed code
                # (the fix is hidden from the writer; see memory/
                # feedback_writer_naive_of_verifier.md). On punt, fall
                # through; attest will emit no_tests_in_pr as before and
                # evict will draft+apology. On success, the committed
                # test rides downstream to attest's fail-on-master gate
                # for independent verification.
                if req.issue:
                    try:
                        await workflow.execute_activity(
                            synth_test_for_fix,
                            args=[req.repo, req.branch, req.worktree,
                                  req.issue, req.issue, None],
                            start_to_close_timeout=timedelta(minutes=12),
                            retry_policy=RetryPolicy(
                                maximum_attempts=1,
                                non_retryable_error_types=["ApplicationError"],
                            ),
                        )
                    except Exception:
                        # Punt path. Attest sees no test, emits the
                        # existing no_tests_in_pr verdict, evict handles.
                        pass

                # qa is pure review (+ allowed edits via the skill); the
                # test gate lives in the downstream attest actor now. The
                # earlier in-actor test_attestation call was a pre-split
                # vestige that double-tested every pass-bound card.
                test_att = None

                diff = await workflow.execute_activity(
                    "git_diff_for_branch",
                    req,
                    start_to_close_timeout=timedelta(seconds=30),
                ) if False else ""  # placeholder — real impl pulls from a small gh activity

                codex_att = await workflow.execute_activity(
                    codex_review,
                    args=[req, diff],
                    start_to_close_timeout=timedelta(minutes=3),
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )

                gemini_first = await workflow.execute_activity(
                    gemini_review,
                    args=[req, diff, 1],
                    start_to_close_timeout=timedelta(minutes=3),
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )
                gemini_last = gemini_first  # real volley iterates more rounds

                # Sonnet shim — authoritative verdict + structured per-
                # reviewer extraction. Replaces the old "verdict=pass"
                # placeholder with a real fuse over both reviewers'
                # prose. Malformed JSON from the shim raises non-
                # retryable → andon, per project decision to trust the
                # shim and pull the cord on outage.
                texts = await workflow.execute_activity(
                    read_artifact_texts,
                    args=[codex_att.artifact_path, gemini_last.artifact_path],
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )
                codex_text = texts["codex"]
                claude_text = texts["claude"]
                shim = await workflow.execute_activity(
                    extract_qa_verdicts,
                    args=[codex_text, claude_text, req.msg_id, req.repo, req.issue],
                    start_to_close_timeout=timedelta(seconds=60),
                    retry_policy=RetryPolicy(
                        maximum_attempts=1,
                        non_retryable_error_types=["ApplicationError"],
                    ),
                )
                codex_att.verdict = shim["codex"]["verdict"]
                gemini_last.verdict = shim["claude"]["verdict"]

                self.last_outcome = QaOneEntryResult(
                    msg_id=req.msg_id,
                    verdict=shim["fused"]["verdict"],
                    bugs_found=0,
                    test_attestation=test_att,
                    codex=codex_att,
                    gemini_first=gemini_first,
                    gemini_last=gemini_last,
                    elapsed_seconds=0.0,
                )

                # Production-lane handoff: qa is now upstream of attest.
                # Pass the (possibly qa-edited) branch to attest, which
                # runs the test gate and on pass forwards to compose.
                # Without this kick the production lane dead-ends here.
                try:
                    if req.branch and req.branch not in ("HEAD", "main", "master"):
                        await workflow.execute_activity(
                            kick_attest_card,
                            args=[req.repo, req.branch, req.issue, "qa", msg],
                            start_to_close_timeout=timedelta(seconds=10),
                        )
                except Exception as e:
                    workflow.logger.warning(
                        "kick_attest failed: msg_id=%s err=%s",
                        msg.msg_id, str(e)[:200],
                    )
            except Exception as e:
                # Walk the cause chain looking for a "skip:"-prefixed
                # ApplicationError. Temporal wraps activity exceptions
                # in ActivityError → cause → ApplicationError, so the
                # marker isn't visible at the top level.
                msg_text = _skip_marker(e)
                if msg_text is not None:
                    workflow.logger.warning(
                        "skip: msg_id=%s reason=%s", msg.msg_id, msg_text
                    )
                else:
                    # Try autofix before declaring an andon. If the
                    # failure text contains a known missing-tool shape
                    # (mold, ruff, tox, protoc, ...), the autofix
                    # activity edits the Dockerfile + dispatches a
                    # rebuild and returns. We then ack the failed card
                    # without halting; the next worker restart picks up
                    # the new image and downstream cards succeed.
                    err_text = f"{type(e).__name__}: {str(e)[:600]}"
                    try:
                        fix = await workflow.execute_activity(
                            "autofix_from_text", args=[err_text],
                            start_to_close_timeout=timedelta(seconds=30),
                        )
                    except Exception:
                        fix = {"handled": False}
                    if fix.get("handled"):
                        workflow.logger.warning(
                            "autofix-self-healed: msg_id=%s tools=%s",
                            msg.msg_id,
                            [r.get("tool") for r in fix.get("results", [])],
                        )
                    else:
                        # Anything else is a contract violation or systemic
                        # surprise — pull the andon cord. Silent retry was
                        # the pre-andon failure mode that hid the missing-
                        # worktree problem across machines.
                        self.halted = True
                        workflow.logger.error(
                            "andon: msg_id=%s type=%s reason=%s",
                            msg.msg_id, type(e).__name__, str(e)[:300],
                        )
                        await workflow.execute_activity(
                            record_andon,
                            args=["qa", msg.msg_id,
                                  f"{type(e).__name__}: {str(e)[:400]}"],
                            start_to_close_timeout=timedelta(seconds=5),
                        )
            # Ack at the view layer whether or not the run passed —
            # the message has been processed; staying "in flight"
            # forever would mask the andon. Operator sees halted=True
            # via cockpit's status badge; the message itself moves on.
            await workflow.execute_activity(
                mark_acked, args=[msg.msg_id],
                start_to_close_timeout=timedelta(seconds=5),
            )
            # Pull signal: qa just freed a slot. Tug rope; rope decides
            # whether roll's inbox needs filling. Best-effort — a
            # missed signal is a missed pull, not a correctness bug.
            try:
                await workflow.execute_activity(
                    kick_rope_card, args=["qa", msg],
                    start_to_close_timeout=timedelta(seconds=5),
                )
            except Exception:
                pass
        finally:
            # Decrement no matter what — exceptions, halts, skips. The
            # dispatcher loop's wait_condition uses this counter to know
            # when there's room to dequeue more work.
            self.in_flight -= 1
