"""SkillActor — generic long-running workflow for any skill-shelling actor.

Each instance owns one inbox (drip, triage, etc.). The skill is
specified at workflow start as `run(activity_name)`; the actor
dispatches `deliver`-signaled messages to that activity by name.

Replaces per-skill workflow modules (DripActor, future TriageActor).
The shape — pending queue, deliver/clear_andon/state, mark_started /
mark_acked bookkeeping, broad-andon-on-exception — was identical
across them; parameterizing on the activity name collapses the clones.

Concurrency stays serial (WIP=1) because skill calls shell out to a
claude subprocess: the human bottleneck (LLM tokens, rate limits) is
better served by one-at-a-time per actor than by burst-then-throttle.
Per-actor concurrency can be added by passing a cap to run() later.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from sweep.activities.worktree import (
        clear_andon_marker,
        mark_acked,
        mark_started,
        record_andon,
    )
    from sweep.types import Message


@workflow.defn
class SkillActor:
    def __init__(self) -> None:
        self._pending: list[Message] = []
        self._seen_msg_ids: set[str] = set()
        self.halted: bool = False
        self.last_outcome: dict | None = None
        self.activity_name: str = ""

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
        if self.activity_name:
            await workflow.execute_activity(
                clear_andon_marker, args=[self.activity_name],
                start_to_close_timeout=timedelta(seconds=5),
            )

    @workflow.query
    def state(self) -> dict:
        return {
            "depth": len(self._pending),
            "halted": self.halted,
            "seen_total": len(self._seen_msg_ids),
            "activity_name": self.activity_name,
        }

    @workflow.run
    async def run(self, activity_name: str) -> None:
        self.activity_name = activity_name
        while True:
            await workflow.wait_condition(
                lambda: bool(self._pending) and not self.halted
            )
            msg = self._pending.pop(0)

            await workflow.execute_activity(
                mark_started, args=[msg.msg_id],
                start_to_close_timeout=timedelta(seconds=5),
            )
            try:
                outcome = await workflow.execute_activity(
                    activity_name, msg,
                    # 35min ceiling — generous enough for /investigate
                    # (deep hypothesis graphs run long); triage/drip
                    # finish in seconds either way.
                    start_to_close_timeout=timedelta(minutes=35),
                    retry_policy=RetryPolicy(
                        maximum_attempts=2,
                        non_retryable_error_types=["ApplicationError"],
                    ),
                )
                self.last_outcome = outcome
            except ApplicationError as e:
                self.halted = True
                workflow.logger.error(
                    "andon: actor=%s msg_id=%s reason=%s",
                    activity_name, msg.msg_id, e.message,
                )
                await workflow.execute_activity(
                    record_andon,
                    args=[activity_name, msg.msg_id, str(e.message or "")],
                    start_to_close_timeout=timedelta(seconds=5),
                )
            except Exception as e:
                self.halted = True
                workflow.logger.error(
                    "andon (unexpected): actor=%s msg_id=%s type=%s reason=%s",
                    activity_name, msg.msg_id, type(e).__name__, str(e)[:300],
                )
                await workflow.execute_activity(
                    record_andon,
                    args=[activity_name, msg.msg_id,
                          f"{type(e).__name__}: {str(e)[:400]}"],
                    start_to_close_timeout=timedelta(seconds=5),
                )
            await workflow.execute_activity(
                mark_acked, args=[msg.msg_id],
                start_to_close_timeout=timedelta(seconds=5),
            )
