"""ProspectPuller — demand-driven replacement for ProspectTicker.

No takt. Fires `prospect_one_pass` whenever the downstream inboxes
have slack and no operator/system gate is held. Polls cheaply (a
filesystem-only `check_pull_conditions` activity) on a short interval;
the interval is operational, not load-bearing — it caps how fast we
respond to capacity opening up, not how fast we pull.

Replaces the old cadence knob with a state report. Cockpit reads it
and shows `prospect: ready` / `prospect: triage full (10/10)` / etc.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from sweep.activities.prospect import (
        ProspectRunRequest,
        check_pull_conditions,
        prospect_one_pass,
    )


# How often to re-check gates when blocked. Short enough that capacity
# opening up gets noticed quickly; long enough that the workflow event
# log doesn't churn while sitting idle.
POLL_S = 30


@workflow.defn
class ProspectPuller:
    def __init__(self) -> None:
        self.last_fire_iso: str = ""
        self.fires_total: int = 0
        self.last_state: str = "init"     # "ready" | "firing" | "blocked: <reason>"
        self.last_depths: dict = {}

    @workflow.query
    def state(self) -> dict:
        return {
            "last_fire_iso": self.last_fire_iso,
            "fires_total": self.fires_total,
            "last_state": self.last_state,
            "last_depths": self.last_depths,
        }

    @workflow.run
    async def run(self) -> None:
        while True:
            check = await workflow.execute_activity(
                check_pull_conditions,
                start_to_close_timeout=timedelta(seconds=10),
            )
            self.last_depths = check.get("depths", {})
            if check.get("can_pull"):
                self.last_state = "firing"
                self.last_fire_iso = workflow.now().isoformat()
                self.fires_total += 1
                try:
                    await workflow.execute_activity(
                        prospect_one_pass,
                        ProspectRunRequest(),  # budget=1 default
                        start_to_close_timeout=timedelta(minutes=5),
                    )
                except Exception as e:
                    workflow.logger.error("prospect pull failed: %s", e)
                self.last_state = "ready"
                # Loop immediately — if there's still slack, fire again.
                # Only sleep when blocked.
                continue
            self.last_state = f"blocked: {check.get('reason', 'unknown')}"
            await workflow.sleep(timedelta(seconds=POLL_S))
