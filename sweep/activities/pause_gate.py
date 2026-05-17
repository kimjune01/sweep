"""pause_gate — inbox-boundary check used by every actor's main loop.

Returns True when the actor should idle (not pull its next message)
because the line is paused, this actor's own budget andon is held, or
(submit-actor only) dry mode is on. The point is to make pause, per-actor
budget, and dry mode into honest "no new work" signals, applied at the
inbox-pull point — never mid-skill.

Dry mode is narrowly scoped: only submit-actor gates on it, because dry
means "no new public commitments" — once a PR is out there, the
maintainer is on real-world time and we owe them a response regardless
of operator pause/dry. Only the new-PR-create path (submit) honors dry.

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
    (qa, remit, notifications, sift, scout).
    """
    from sweep import budget, control_state
    if control_state.is_paused():
        return True
    budget_key = actor_name.removesuffix("_cycle")
    # Submit-actor only: dry mode holds the queue. Cards pile in submit.jsonl;
    # operator inspects via `sweep inbox actor submit`; `sweep dry off`
    # drains. No special code path for dry — just time.
    if budget_key == "submit" and control_state.is_dry():
        return True
    return budget.is_blocked(budget_key)
