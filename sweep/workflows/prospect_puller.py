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
        auto_evict_stale_repos,
        check_pull_conditions,
        loosen_floor,
        prospect_recency_window,
        reset_floor,
    )


# AIMD-style control on min_complexity:
#   • EMPTY_STREAK_LOOSEN_THRESHOLD empties in a row → loosen one rung
#     (the "multiplicative decrease" — we drop the floor to keep work
#     flowing once the substrate clearly isn't producing matches).
#   • triage utilization above HIGH_UTIL_RESET (a healthy queue) → snap
#     back to the operator's target floor (the "additive increase",
#     except it's not additive — it's a snap, since the operator's
#     preference is the canonical target).
# Operator still owns the upward direction beyond target by editing
# ~/.sweep/control/min_complexity_target manually.
#
# Second axis when floor is already at bottom: widen the recency window
# exponentially. Trivial fixes are off the table even when the
# dashboard is empty (operator preference), so the only remaining
# adjustment when SHALLOW still finds nothing is to look further back
# in time. Doubles per failed loosen, capped at 1 year.
EMPTY_STREAK_LOOSEN_THRESHOLD = 5
HIGH_UTIL_RESET = 0.5  # triage queue ≥ 50% of cap → recovery
DAYS_DEFAULT = 30
DAYS_MAX = 365


# How often to re-check gates when blocked. Short enough that capacity
# opening up gets noticed quickly; long enough that the workflow event
# log doesn't churn while sitting idle.
POLL_S = 30


@workflow.defn
class ProspectPuller:
    def __init__(self) -> None:
        self.last_fire_iso: str = ""
        self.fires_total: int = 0
        # Run the eviction sweep every Nth fire (cheap-ish — it
        # reads outcomes which has its own cache). 20 fires ≈
        # every ~5min at the 15s floor, which is fine for a
        # signal that takes days to accumulate.
        self.evict_every: int = 20
        self.last_state: str = "init"     # "ready" | "firing" | "blocked: <reason>"
        self.last_depths: dict = {}
        # Empty-streak: consecutive fires where considered>0 but
        # deposited==0. Long streak = filter too strict OR recency
        # window too narrow OR nothing fresh in the wild. Resets the
        # moment a fire deposits at least one issue.
        self.empty_streak: int = 0
        self.last_considered: int = 0
        self.last_deposited: int = 0
        # Second adjustment axis (kicks in when floor is at SHALLOW
        # and we still can't find work): widen the recency window
        # exponentially. Doubles per failed loosen, capped at DAYS_MAX.
        # Reset to DAYS_DEFAULT on recovery (alongside the floor reset).
        self.days: int = DAYS_DEFAULT

    @workflow.query
    def state(self) -> dict:
        return {
            "last_fire_iso": self.last_fire_iso,
            "fires_total": self.fires_total,
            "last_state": self.last_state,
            "last_depths": self.last_depths,
            "empty_streak": self.empty_streak,
            "last_considered": self.last_considered,
            "last_deposited": self.last_deposited,
            "days": self.days,
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
                    result = await workflow.execute_activity(
                        prospect_recency_window,
                        ProspectRunRequest(days=self.days),
                        # 15 min: a single fire can run hundreds of LLM
                        # judges on warm-org surplus, ~1-2s each. 5min
                        # was too tight and triggered CancelledError
                        # cascades.
                        start_to_close_timeout=timedelta(minutes=15),
                    )
                    considered = int(result.get("considered", 0)) if isinstance(result, dict) else 0
                    deposited = int(result.get("deposited", 0)) if isinstance(result, dict) else 0
                    self.last_considered = considered
                    self.last_deposited = deposited
                    if deposited > 0:
                        self.empty_streak = 0
                    elif considered > 0:
                        # Saw issues, filters rejected them all — streak.
                        self.empty_streak += 1
                        if self.empty_streak >= EMPTY_STREAK_LOOSEN_THRESHOLD:
                            # First axis: try to loosen the floor.
                            r = await workflow.execute_activity(
                                loosen_floor,
                                start_to_close_timeout=timedelta(seconds=5),
                            )
                            if not r.get("changed"):
                                # Floor already at SHALLOW. Second axis:
                                # widen the recency window exponentially.
                                # Trivial is permanently off the table
                                # (operator preference), so look further
                                # back in time instead.
                                if self.days < DAYS_MAX:
                                    new_days = min(self.days * 2, DAYS_MAX)
                                    workflow.logger.warning(
                                        "widening window: %dd → %dd "
                                        "(floor already at SHALLOW)",
                                        self.days, new_days,
                                    )
                                    self.days = new_days
                            self.empty_streak = 0
                    # considered==0 means search returned nothing; not a
                    # filter-rejection signal, leave streak unchanged.

                    # AIMD recovery: if triage is healthy after this
                    # fire, snap floor AND window back to defaults.
                    triage_q = self.last_depths.get("triaged", 0)
                    triage_cap = 10  # mirrors prospect.py
                    if triage_q / triage_cap >= HIGH_UTIL_RESET:
                        await workflow.execute_activity(
                            reset_floor,
                            start_to_close_timeout=timedelta(seconds=5),
                        )
                        if self.days != DAYS_DEFAULT:
                            workflow.logger.info(
                                "window reset: %dd → %dd (recovery)",
                                self.days, DAYS_DEFAULT,
                            )
                            self.days = DAYS_DEFAULT
                except Exception as e:
                    workflow.logger.error("prospect pull failed: %s", e)
                self.last_state = "ready"
                # Periodic eviction sweep — repos with N consecutive
                # closed-unmerged outcomes get added to the auto-
                # evicted file. Runs every Nth fire; cheap because
                # outcomes() is cached upstream.
                if self.fires_total % self.evict_every == 0:
                    try:
                        await workflow.execute_activity(
                            auto_evict_stale_repos,
                            start_to_close_timeout=timedelta(seconds=30),
                        )
                    except Exception as e:
                        workflow.logger.warning("eviction sweep failed: %s", e)
                # Minimum spacing between fires: even when there's
                # slack, don't tight-loop. The recency window doesn't
                # refill faster than gh's search indexing anyway, and
                # rate-of-fires far above ingest rate just burns API
                # quota and produces noise events. 15s is the floor.
                await workflow.sleep(timedelta(seconds=15))
                continue
            self.last_state = f"blocked: {check.get('reason', 'unknown')}"
            await workflow.sleep(timedelta(seconds=POLL_S))
