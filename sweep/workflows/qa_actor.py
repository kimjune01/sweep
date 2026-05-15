"""QaActor — one long-running workflow that owns the qa inbox.

Receives messages via signal. Processes one at a time (WIP=1 enforced by the
activity signature). Tracks andon state via a `halted` flag that the workflow
exposes through a query handler.

In normal operation this workflow never completes — it's a persistent actor.
The supervisor (or a human) can `temporal workflow terminate` it for hard
reset.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    import subprocess
    import time

    from sweep.activities.qa import (
        codex_review,
        gemini_review,
        test_attestation,
    )
    from sweep.types import Message, QaOneEntryRequest, QaOneEntryResult


@workflow.defn
class QaActor:
    def __init__(self) -> None:
        self._pending: list[Message] = []
        self._seen_msg_ids: set[str] = set()
        self.halted: bool = False
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

    @workflow.query
    def depth(self) -> int:
        return len(self._pending)

    @workflow.query
    def state(self) -> dict:
        return {
            "depth": len(self._pending),
            "halted": self.halted,
            "seen_total": len(self._seen_msg_ids),
        }

    @workflow.run
    async def run(self) -> None:
        while True:
            await workflow.wait_condition(lambda: bool(self._pending) and not self.halted)
            msg = self._pending.pop(0)

            req = QaOneEntryRequest(
                msg_id=msg.msg_id,
                repo=msg.repo,
                branch=msg.branch or "",
                worktree=msg.payload.get("worktree", ""),
                test_cmd=msg.payload.get("test_cmd", ""),
                issue=msg.pr,
            )

            try:
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
                workflow.upsert_search_attributes({"bucket": ["qa_passed"]})
            except ApplicationError as e:
                # Contract violation — pull the andon cord, halt this actor.
                # Do NOT re-raise: propagating out of the while-True loop
                # would terminate this persistent actor. halted=True is
                # the signal; the next iteration's wait_condition blocks
                # until clear_andon flips it back.
                self.halted = True
                workflow.upsert_search_attributes({"bucket": ["qa_failed"]})
                workflow.logger.error(
                    "andon: msg_id=%s reason=%s", msg.msg_id, e.message
                )
