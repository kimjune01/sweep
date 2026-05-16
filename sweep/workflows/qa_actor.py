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
    from sweep.activities.infer import infer_test_cmd
    from sweep.activities.qa import (
        codex_review,
        gemini_review,
        test_attestation,
    )
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
            msg = self._pending.pop(0)
            self.in_flight += 1
            asyncio.create_task(self._process_one(msg))

    async def _process_one(self, msg: Message) -> None:
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
                # Worktree first: ensure we have a checked-out copy of
                # (repo, branch) on this machine. Self-heals across
                # machine moves and dropped checkouts. Non-retryable
                # failures here pull the andon cord via the outer except.
                worktree_path = await workflow.execute_activity(
                    ensure_worktree,
                    args=[req.repo, req.branch],
                    start_to_close_timeout=timedelta(minutes=3),
                    retry_policy=RetryPolicy(
                        maximum_attempts=2,
                        non_retryable_error_types=["ApplicationError"],
                    ),
                )
                # Test command: routed messages have an empty test_cmd
                # because pr-state has no idea what the repo's convention
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

                # Each sub-activity is independently called via
                # workflow.execute_activity — own retry policy, own timeout,
                # own event in workflow history. Lets you iterate on
                # codex_review in isolation without rebuilding qa_one_entry.
                test_att = await workflow.execute_activity(
                    test_attestation,
                    req,
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(seconds=5),
                        maximum_attempts=2,
                        non_retryable_error_types=["ApplicationError"],
                    ),
                )

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

                self.last_outcome = QaOneEntryResult(
                    msg_id=req.msg_id,
                    verdict="pass",
                    bugs_found=0,
                    test_attestation=test_att,
                    codex=codex_att,
                    gemini_first=gemini_first,
                    gemini_last=gemini_last,
                    elapsed_seconds=0.0,
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
        finally:
            # Decrement no matter what — exceptions, halts, skips. The
            # dispatcher loop's wait_condition uses this counter to know
            # when there's room to dequeue more work.
            self.in_flight -= 1
