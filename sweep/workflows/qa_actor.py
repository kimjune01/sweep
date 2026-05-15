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
    from sweep.activities.qa import qa_one_entry
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
                self.last_outcome = await workflow.execute_activity(
                    qa_one_entry,
                    req,
                    start_to_close_timeout=timedelta(minutes=10),
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(seconds=10),
                        maximum_attempts=3,
                        non_retryable_error_types=["ApplicationError"],
                    ),
                )
                workflow.upsert_search_attributes({"bucket": ["qa_passed"]})
            except ApplicationError as e:
                # Contract violation — pull the andon cord, halt this actor.
                self.halted = True
                workflow.upsert_search_attributes({"bucket": ["qa_failed"]})
                # Re-raise to mark the workflow attempt as failed in history.
                # Temporal still keeps the workflow execution running because
                # this is inside a loop — the next iteration only proceeds
                # after clear_andon.
                workflow.logger.error(
                    "andon: msg_id=%s reason=%s", msg.msg_id, e.message
                )
