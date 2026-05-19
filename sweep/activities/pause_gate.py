"""pause_gate — inbox-boundary check used by every actor's main loop.

Returns True when the actor should idle (not pull its next message)
because the line is paused, this actor's own budget andon is held, or
(submit-actor only) dry mode is on. The point is to make pause, per-actor
budget, and dry mode into honest "no new work" signals, applied at the
inbox-pull point — never mid-skill.

Dry mode is narrowly scoped: only submit-actor gates on it, because
dry means "no new public commitments." `gh pr edit` is silent under
default GitHub notification settings (description edits don't ping
watchers / reviewers / authors), so amend runs through dry. Edits
still appear in the PR's activity timeline, which a maintainer
scrolling back will see — that's the residual "invisible cost" —
but it's not a notification surface. Engagement actors (respond,
reqa) likewise don't honor dry — once a PR is out there, the
maintainer is on real-world time and we owe them a reply.

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
    (qa, remit, notifications, sift, roll).
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
    # Ping/post/comment-issue: the `post_disabled` flag is the single safety
    # latch for every maintainer-visible action. When set, these
    # actors park at the inbox boundary — cards accumulate in their
    # jsonl files rather than being consumed-then-skipped, so flipping
    # the flag back off drains the held queue as a single burst-on-
    # resume. Without this, "skipped while disabled" is lossy.
    if budget_key in ("ping", "post", "comment-issue"):
        from pathlib import Path as _P
        if (_P.home() / ".sweep" / "control" / "post_disabled").exists():
            return True
    # Per-actor pause file. Operator drops
    # `~/.sweep/control/actor_paused/<actor>` to temporarily halt a
    # single actor without affecting the rest of the line (vs global
    # `sweep pause on` which idles everyone). Use case: operator-paced
    # heijunka — let one over-burning actor drain its queue gradually
    # while others keep working. Distinct from `~/.sweep/control/paused`
    # which is the global pause flag set by record_andon.
    from pathlib import Path as _P
    if (_P.home() / ".sweep" / "control" / "actor_paused" / budget_key).exists():
        return True
    # Per-actor throttle (operator-paced heijunka). Config + counter
    # logic live in `budget.is_throttled`; pause_gate just consults.
    if budget.is_throttled(budget_key):
        return True
    return budget.is_blocked(budget_key)
