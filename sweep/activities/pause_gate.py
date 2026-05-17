"""pause_gate — inbox-boundary check used by every actor's main loop.

Returns True when the actor should idle (not pull its next message)
because the line is paused or this actor's own budget andon is held.
The point is to make pause and per-actor budget into honest "no new
work" signals, applied at the inbox-pull point — never mid-skill.

Cheap: two filesystem stats per call.
"""

from __future__ import annotations

from temporalio import activity


@activity.defn
async def should_idle(actor_name: str) -> bool:
    """True if the actor should pause before its next inbox pull.

    actor_name may arrive as the activity name (e.g. 'triage_cycle')
    from SkillActor; map to the budget share key by stripping '_cycle'
    so per-actor budget gating works uniformly. Falls back to actor_name
    unchanged for actors whose name matches a budget key already
    (qa, pr-state, notifications, prospect).
    """
    from sweep import budget, control_state
    if control_state.is_paused():
        return True
    budget_key = actor_name.removesuffix("_cycle")
    return budget.is_blocked(budget_key)
