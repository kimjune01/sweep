"""Ship — the new-PR-create gate.

Sits between qa's verified fix (eventually via compose-actor) and
respond's push. Single job: gate the new-public-commitment moment.

Three things ship does that no upstream actor does:

  1. Honors dry mode. Dry is narrowly scoped — it means "no new public
     commitments" — and ship is the only actor that gates on it. The
     gating happens at the inbox-pull point (pause_gate.should_idle) so
     cards pile in ship.jsonl while dry is on; `sweep dry off` drains.

  2. Final-bastion re-verify. Attestation hash + repo eviction + AI
     policy + still-mergeable. Cheap re-checks against live state right
     before the push, in case the world moved while the card waited.
     (Full battery lands in a follow-up; this skeleton trusts upstream.)

  3. Delegates the actual push. Once gates pass, ship hands off to
     respond-actor with intent="publish" — respond owns the /drip
     subprocess and the budget attribution for the gh calls.

The split lets ship stay small and auditable (a list of gates) while
respond stays mechanical (push verbs). Different concerns, different
actors.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict
from pathlib import Path

from temporalio import activity
from temporalio.exceptions import ApplicationError

from sweep.types import Message

SHIP_INBOX = Path.home() / ".sweep" / "inbox" / "ship.jsonl"


@activity.defn
async def kick_ship_card(repo: str, branch: str, pr: int | None = None,
                         sender: str = "qa",
                         attestation_hash: str | None = None) -> str | None:
    """Deposit a ready-to-publish card on ship.jsonl and signal
    ship-actor. Called by qa (eventually compose) when a fix is
    verified and ready to land as a new PR or push.

    Card carries the publish-time inputs: repo, branch, optional pr
    number (rebase to existing PR vs. new), and attestation hash for
    ship's re-verify step."""
    from sweep import observe
    from sweep.activities.pr_state import _signal_actor

    ts = dt.datetime.now(dt.timezone.utc)
    slug = repo.replace("/", "-")
    pr_part = pr if pr is not None else "new"
    msg_id = f"ship-{ts.strftime('%Y%m%dT%H%M%S')}-{slug}-{pr_part}"
    payload = {}
    if attestation_hash:
        payload["attestation_hash"] = attestation_hash
    msg = Message(
        msg_id=msg_id,
        sender=sender,
        intent="publish",
        repo=repo,
        pr=pr,
        branch=branch,
        payload=payload,
        ts=ts.isoformat(),
    )
    SHIP_INBOX.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(SHIP_INBOX, "a") as f:
            f.write(json.dumps(asdict(msg)) + "\n")
    except Exception as e:
        observe.event("ship_card_write_failed", repo=repo, branch=branch,
                      error_type=type(e).__name__, error=str(e)[:200])
        return None
    observe.event("ship_card_deposited", repo=repo, branch=branch,
                  pr=pr, sender=sender, msg_id=msg_id)
    return await _signal_actor("ship", msg)


@activity.defn
async def ship_cycle(msg: Message) -> dict:
    """Gate one publish card and delegate the push to respond.

    Dry-mode hold lives upstream at pause_gate (the actor doesn't even
    pull the card while dry is on), so by the time this activity runs
    we know dry is off. The final-check battery is the gate; respond is
    the doer.

    Skeleton version: trusts upstream's prep, runs the publish via
    respond_cycle. Final checks land in a follow-up commit.
    """
    if not msg.repo or not msg.branch:
        raise ApplicationError("ship: repo + branch required",
                               non_retryable=True)
    from sweep import observe
    from sweep.activities.skill_runner import respond_cycle

    # Synthesize a respond-shaped message and delegate. respond_cycle
    # records its own subprocess budget and runs /drip --push.
    publish_msg = Message(
        msg_id=f"{msg.msg_id}-publish",
        sender="ship",
        intent="publish",
        repo=msg.repo,
        pr=msg.pr,
        branch=msg.branch,
        payload=msg.payload,
        ts=dt.datetime.now(dt.timezone.utc).isoformat(),
    )
    result = await respond_cycle(publish_msg)
    observe.event("ship_published", repo=msg.repo, branch=msg.branch,
                  pr=msg.pr, rc=result.get("rc", 0),
                  msg_id=msg.msg_id)
    return {"published": True, "respond_result": result}
