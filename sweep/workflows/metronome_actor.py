"""MetronomeActor — cadence-driven kicker with mailbox.

An actor (not a daemon) whose job is to fire other actors on a clock.
Sleeps to the next scheduled tick, then runs `metronome_tick` to kick
whichever targets are due. Also accepts manual kicks via the `deliver`
signal — operators or other actors can deposit a tick card to force
an immediate evaluation pass.

Has feelings: pause_gate at the loop boundary (paused → skip the tick,
re-sleep), andon-able on activity exception, state queryable from the
cockpit.

Schedule is module-local for now; if it grows, externalize to a config
file but keep the actor responsible for reading it.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from sweep.activities.metronome import metronome_tick
    from sweep.activities.pause_gate import should_idle
    from sweep.activities.worktree import clear_andon_marker, record_andon
    from sweep.types import Message


ACTOR_NAME = "metronome"
# Wake at least this often to re-evaluate the schedule even if no
# entry is due — covers schedule edits applied via worker restart.
MAX_SLEEP = timedelta(minutes=15)
MIN_SLEEP = timedelta(seconds=10)


@workflow.defn
class MetronomeActor:
    def __init__(self) -> None:
        self._pending: list[Message] = []
        self._seen_msg_ids: set[str] = set()
        self.halted: bool = False
        self.last_tick_iso: str = ""
        self.ticks_total: int = 0
        self.last_result: dict | None = None

    @workflow.signal
    async def deliver(self, msg: Message) -> None:
        """Manual kick from operator or another actor. Idempotent."""
        if msg.msg_id in self._seen_msg_ids:
            return
        self._seen_msg_ids.add(msg.msg_id)
        self._pending.append(msg)

    @workflow.signal
    async def clear_andon(self) -> None:
        self.halted = False
        await workflow.execute_activity(
            clear_andon_marker, args=[ACTOR_NAME],
            start_to_close_timeout=timedelta(seconds=5),
        )

    @workflow.query
    def state(self) -> dict:
        return {
            "depth": len(self._pending),
            "halted": self.halted,
            "last_tick_iso": self.last_tick_iso,
            "ticks_total": self.ticks_total,
            "last_result": self.last_result,
            "activity_name": "metronome_tick",
        }

    @workflow.run
    async def run(self) -> None:
        while True:
            # Wake on manual kick OR scheduled tick. Sleep is bounded
            # by MAX_SLEEP so we never miss an externally-edited schedule.
            try:
                await workflow.wait_condition(
                    lambda: bool(self._pending) and not self.halted,
                    timeout=MAX_SLEEP,
                )
            except TimeoutError:
                pass  # cadence wake — normal path

            # Pause gate at the boundary. Paused pipeline → skip the tick.
            if await workflow.execute_activity(
                should_idle, args=[ACTOR_NAME],
                start_to_close_timeout=timedelta(seconds=5),
                retry_policy=RetryPolicy(maximum_attempts=2),
            ):
                await workflow.sleep(MIN_SLEEP)
                continue

            if self.halted:
                await workflow.sleep(MIN_SLEEP)
                continue

            # Drain at most one manual kick per loop turn (WIP=1 semantics).
            manual_msg = self._pending.pop(0) if self._pending else None

            try:
                result = await workflow.execute_activity(
                    metronome_tick,
                    args=[manual_msg] if manual_msg else [],
                    start_to_close_timeout=timedelta(seconds=60),
                    retry_policy=RetryPolicy(
                        maximum_attempts=2,
                        non_retryable_error_types=["ApplicationError"],
                    ),
                )
                self.last_result = result
            except ApplicationError as e:
                self.halted = True
                workflow.logger.error(
                    "metronome andon: %s", e.message,
                )
                await workflow.execute_activity(
                    record_andon,
                    args=[ACTOR_NAME, manual_msg.msg_id if manual_msg else "tick",
                          str(e.message or "")],
                    start_to_close_timeout=timedelta(seconds=5),
                )
                continue
            except Exception as e:
                workflow.logger.warning("metronome tick failed: %s", e)
                self.last_result = {"error": str(e)[:200]}

            self.last_tick_iso = workflow.now().isoformat()
            self.ticks_total += 1

            # Sleep until next due. Activity returns next_due_seconds;
            # clamp to [MIN_SLEEP, MAX_SLEEP] so a bug in the schedule
            # can't burn CPU or stall the actor indefinitely.
            next_due = (self.last_result or {}).get("next_due_seconds")
            if isinstance(next_due, (int, float)) and next_due > 0:
                sleep_for = max(
                    MIN_SLEEP, min(MAX_SLEEP, timedelta(seconds=next_due))
                )
            else:
                sleep_for = MAX_SLEEP
            await workflow.sleep(sleep_for)
