"""LeakdogDaemon — sniffs for leaks on a tick independent of any
other workflow's health.

Today's job: clear the API-budget andon when projected utilization
has actually recovered. This logic also lives inside the sift
puller's gate, but a wedged puller can't recover its own andon —
hence the independent tick. See [[O2]].

Future: this daemon is the natural place to surface interface
leakdog warnings as events when the funnel imbalance crosses a
threshold (e.g. emit `leakdog_interface_warning` when any
sift→triage residual exceeds N for >M minutes).

Cadence: 60s. Short enough that an API-budget recovery is visible
within a minute; long enough that the leakdog tick itself doesn't
become a meaningful API consumer.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from sweep.activities.leakdog import leakdog_tick


TICK_SECONDS = 60


@workflow.defn
class LeakdogDaemon:
    def __init__(self) -> None:
        self.last_tick_iso: str = ""
        self.ticks_total: int = 0
        self.last_result: dict | None = None

    @workflow.query
    def state(self) -> dict:
        return {
            "last_tick_iso": self.last_tick_iso,
            "ticks_total": self.ticks_total,
            "last_result": self.last_result,
            "tick_seconds": TICK_SECONDS,
        }

    @workflow.run
    async def run(self) -> None:
        while True:
            try:
                result = await workflow.execute_activity(
                    leakdog_tick,
                    start_to_close_timeout=timedelta(seconds=10),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
                self.last_result = result
            except Exception as e:
                # Leakdog never andons (would be ironic). Log and continue.
                workflow.logger.warning("leakdog tick failed: %s", e)
                self.last_result = {"error": str(e)[:200]}
            self.last_tick_iso = workflow.now().isoformat()
            self.ticks_total += 1
            await workflow.sleep(timedelta(seconds=TICK_SECONDS))
