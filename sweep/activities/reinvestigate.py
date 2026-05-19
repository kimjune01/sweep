"""Reinvestigate — engagement-lane investigate.

Same /investigate skill, different application: this actor runs on
existing PRs where the maintainer raised a concern or CI failed in a
non-mechanical way. The card always carries an msg.pr; if it doesn't,
something routed the wrong shape and we fail-fast (non-retryable) so
the misroute surfaces instead of running an investigation against a
bogus card.

Downstream: on a fresh artifact with a fix shape, kicks reqa-actor for
verification before respond pushes to the existing branch. Compose and
submit are skipped — the PR already exists; we're patching, not
creating.

The investigate skill code itself is unchanged. The split lets us
evolve precondition/routing/observability independently from the
production lane (triaged → investigate → qa → compose → submit →
respond) when the two flavors diverge.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict
from pathlib import Path

from temporalio import activity
from temporalio.exceptions import ApplicationError

from sweep.types import Message, forward_ledger


REINVESTIGATE_INBOX = Path.home() / ".sweep" / "inbox" / "reinvestigate.jsonl"


@activity.defn
async def kick_reinvestigate_card(repo: str, pr: int,
                                  sender: str = "remit",
                                  incoming: Message | None = None) -> str | None:
    """Deposit a reinvestigate card on reinvestigate.jsonl and signal
    reinvestigate-actor. Called by remit when a PR classifies into
    bucket=reinvestigate (maintainer_raised_concern or non-mechanical
    CI failure on an existing PR)."""
    from sweep import observe
    from sweep.activities.pr_state import _signal_actor

    ts = dt.datetime.now(dt.timezone.utc)
    slug = repo.replace("/", "-")
    msg_id = f"reinvestigate-{ts.strftime('%Y%m%dT%H%M%S')}-{slug}-{pr}"
    msg = Message(
        msg_id=msg_id,
        sender=sender,
        intent="diagnose-followup",
        repo=repo,
        pr=pr,
        branch=None,
        payload={},
        ts=ts.isoformat(),
        ledger=forward_ledger(incoming),
    )
    REINVESTIGATE_INBOX.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(REINVESTIGATE_INBOX, "a") as f:
            f.write(json.dumps(asdict(msg)) + "\n")
    except Exception as e:
        observe.event("reinvestigate_card_write_failed", repo=repo, pr=pr,
                      error_type=type(e).__name__, error=str(e)[:200])
        return None
    observe.event("reinvestigate_card_deposited", repo=repo, pr=pr,
                  sender=sender, msg_id=msg_id)
    return await _signal_actor("reinvestigate", msg)


@activity.defn
async def reinvestigate_cycle(msg: Message) -> dict:
    """Run /investigate on an existing-PR concern; on a fix, kick reqa.

    Precondition: msg.pr required. Without a PR number this card was
    misrouted (production-lane investigate handles new issues).
    """
    if msg.intent == "nudge":
        return {"outcome": "nudge-noop"}
    if not msg.pr:
        raise ApplicationError(
            "reinvestigate: msg.pr required (engagement-lane only); "
            "new-issue investigations belong on investigate.jsonl",
            non_retryable=True,
        )

    from sweep import budget as _budget, observe, pokayoke
    from sweep.activities.skill_runner import investigate_cycle
    from sweep.activities.reqa import kick_reqa_card

    skip = pokayoke.reinvestigate_intake(msg)
    if skip:
        observe.event("reinvestigate_skipped", repo=msg.repo, pr=msg.pr,
                      reason=skip.code, detail=skip.detail,
                      msg_id=msg.msg_id)
        # Mirror as `reinvestigate_done` so retro skill-stats and other
        # consumers keyed on the terminal event still bucket the skip
        # instead of treating it as a silent drop.
        observe.event("reinvestigate_done", repo=msg.repo, pr=msg.pr,
                      outcome="skipped", reason=skip.code,
                      msg_id=msg.msg_id)
        return {"outcome": "skipped", "reason": skip.code}

    # Tag caller so gh-io subprocess attribution lands on reinvestigate's
    # budget, not investigate's. Critical for the budget split: without
    # this, the inner subprocess estimate still records against
    # "investigate" via the hardcoded record_subprocess_estimate call
    # in _investigate_cycle_inner.
    _budget.set_caller("reinvestigate")

    # Delegate to the shared investigate flow. investigate_cycle emits
    # its own `investigate_done` event for the artifact; we add a
    # `reinvestigate_done` event so leakdog can balance the engagement-
    # lane funnel separately from production.
    result = await investigate_cycle(msg)
    observe.event(
        "reinvestigate_done",
        repo=msg.repo,
        pr=msg.pr,
        produced_pr=bool(result.get("produced_pr")),
        no_fix=bool(result.get("no_fix")),
        human_gated=bool(result.get("human_gated")),
        artifact_fresh=bool(result.get("artifact_fresh")),
    )

    # On a fresh fix that isn't a no-fix or human-gated halt, hand off
    # to reqa for verification before respond pushes. Investigate's
    # comment-issue side-hatch already fires for no-fix; we don't duplicate it.
    if result.get("artifact_fresh") and not (result.get("no_fix") or result.get("human_gated")):
        try:
            await kick_reqa_card(
                msg.repo, int(msg.pr),
                branch=result.get("branch"),
                sender="reinvestigate",
                incoming=msg,
            )
        except Exception as e:
            observe.event("kick_reqa_failed", repo=msg.repo, pr=msg.pr,
                          error_type=type(e).__name__, error=str(e)[:200])

    return result
