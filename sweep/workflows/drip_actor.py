"""DripActor — one long-running workflow that owns the drip inbox.

Mirrors QaActor's shape: a `deliver` signal accepts Message; a
`clear_andon` signal flips `halted` back off; `state` query exposes
depth + halted for the cockpit. The run loop processes one message
at a time (WIP=1, matching the drip station's cap — one PR push per
repo at a time is the whole pacing point).

Each message becomes one `drip_cycle` activity invocation, which
shells out to the /drip skill via claude. Failures pull the andon
cord. View-layer start/ack markers fire via the worktree module's
mark_started / mark_acked so the cockpit's in-flight column reflects
real progress.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from sweep.activities.drip import drip_cycle
    from sweep.activities.worktree import mark_acked, mark_started
    from sweep.types import Message


@workflow.defn
class DripActor:
    def __init__(self) -> None:
        self._pending: list[Message] = []
        self._seen_msg_ids: set[str] = set()
        self.halted: bool = False
        self.last_outcome: dict | None = None

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

            await workflow.execute_activity(
                mark_started, args=[msg.msg_id],
                start_to_close_timeout=timedelta(seconds=5),
            )

            try:
                outcome = await workflow.execute_activity(
                    drip_cycle,
                    msg,
                    start_to_close_timeout=timedelta(minutes=12),
                    retry_policy=RetryPolicy(
                        maximum_attempts=2,
                        non_retryable_error_types=["ApplicationError"],
                    ),
                )
                self.last_outcome = outcome
            except ApplicationError as e:
                self.halted = True
                workflow.logger.error(
                    "andon: msg_id=%s reason=%s", msg.msg_id, e.message
                )
            except Exception as e:
                # Broader andon — same rule as QaActor: silent retry
                # masks systemic problems (claude not on PATH, OS error).
                self.halted = True
                workflow.logger.error(
                    "andon (unexpected): msg_id=%s type=%s reason=%s",
                    msg.msg_id, type(e).__name__, str(e)[:300],
                )

            await workflow.execute_activity(
                mark_acked, args=[msg.msg_id],
                start_to_close_timeout=timedelta(seconds=5),
            )
