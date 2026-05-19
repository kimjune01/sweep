"""Remit — the PR-state router actor.

Receives raw "PR X changed state" cards from NotificationPoller (or any
other emitter), classifies via classify_one_pr, and routes to the
matching downstream actor (qa, investigate, respond, comment-issue, etc.) or
deposits to the human inbox (human.jsonl).

Replaces the inline gh_pr_view → classify_one_pr → deliver_to_inbox
chain that used to live inside NotificationPoller. Pulling it into a
named actor makes the post-ship engagement loop a first-class thing
instead of a routing side-effect, and lets the poller stay a dumb
emitter (its only job: turn GitHub notifications into local cards).

Why "remit": dispatching a PR to the right downstream is squarely
within this actor's remit. The verb captures the act of sending; the
noun ("within remit") captures the scope ownership.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
from dataclasses import asdict
from pathlib import Path

from temporalio import activity
from temporalio.exceptions import ApplicationError

from sweep.types import Message, forward_ledger

REMIT_INBOX = Path.home() / ".sweep" / "inbox" / "remit.jsonl"


@activity.defn
async def kick_remit_card(repo: str, pr: int,
                          sender: str = "notification-poller",
                          thread_id: str | None = None,
                          incoming: Message | None = None) -> str | None:
    """Deposit one raw PR-state-changed card on remit.jsonl and signal
    remit-actor. Used by NotificationPoller (steady-state) and the
    leakdog's `_seed_unclassified_prs` tick (safety-net rescan).

    Caller passes (repo, pr); remit-actor fetches live state and
    classifies. The card carries no classification — that's deliberate,
    so remit owns the policy of *how* to classify."""
    from sweep import observe
    from sweep.activities.pr_state import _signal_actor

    ts = dt.datetime.now(dt.timezone.utc)
    slug = repo.replace("/", "-")
    msg_id = f"remit-{ts.strftime('%Y%m%dT%H%M%S')}-{slug}-{pr}"
    msg = Message(
        msg_id=msg_id,
        sender=sender,
        intent="classify",
        repo=repo,
        pr=pr,
        branch=None,
        payload={"thread_id": thread_id} if thread_id else {},
        ts=ts.isoformat(),
        ledger=forward_ledger(incoming),
    )
    REMIT_INBOX.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(REMIT_INBOX, "a") as f:
            f.write(json.dumps(asdict(msg)) + "\n")
    except Exception as e:
        observe.event("remit_card_write_failed", repo=repo, pr=pr,
                      error_type=type(e).__name__, error=str(e)[:200])
        return None
    observe.event("remit_card_deposited", repo=repo, pr=pr,
                  sender=sender, msg_id=msg_id)
    return await _signal_actor("remit", msg)


@activity.defn
async def remit_cycle(msg: Message) -> dict:
    """One classify-and-route pass on one raw PR card.

    Pulls live PR state, classifies into a bucket, and delivers to the
    bucket's destination inbox (which may also signal a downstream
    actor). The classifier and delivery logic live in pr_state.py — this
    activity is the actor's adapter around them.

    Returns {bucket, delivered_to, reason} so the actor's event log
    carries the decision shape.
    """
    if not msg.repo or not msg.pr:
        raise ApplicationError("remit: repo + pr required",
                               non_retryable=True)
    from sweep import observe
    from sweep.activities.pr_state import (
        classify_one_pr,
        deliver_to_inbox,
        gh_pr_view,
    )

    try:
        state = await gh_pr_view(msg.repo, int(msg.pr))
    except ApplicationError as e:
        # "Could not resolve to a PullRequest" = the number is an issue,
        # not a PR (or the PR was hard-deleted). Either way, remit has
        # nothing to classify — noop with a clear event instead of
        # halting the actor.
        emsg = str(e.message or "")
        if "Could not resolve to a PullRequest" in emsg:
            observe.event("remit_skipped", repo=msg.repo, pr=msg.pr,
                          reason="not_a_pr",
                          msg_id=msg.msg_id)
            return {"bucket": "skip", "delivered_to": "sink",
                    "reason": "not_a_pr"}
        raise

    # Trigger override: when a `check` actor card lands here ahead of
    # the live `statusCheckRollup` updating, the gh fetch may still
    # show ci=pending while we already know a specific check failed.
    # Honor `payload.trigger == "ci_check_failed"` by forcing the
    # derived `ci`/`failing_check` to match what the upstream emitter
    # observed. Without this, the external-ratification signal silently
    # races and re-derives to whatever gh happens to show right now.
    payload = msg.payload or {}
    if payload.get("trigger") == "ci_check_failed":
        check_name = str(payload.get("check_name") or "") or state.failing_check
        state = dataclasses.replace(state, ci="failing", failing_check=check_name)

    classified = await classify_one_pr(state)
    delivered = await deliver_to_inbox(classified)
    observe.event("remit_delivered", repo=msg.repo, pr=msg.pr,
                  bucket=classified.bucket,
                  delivered_to=delivered,
                  reason=classified.reason[:200])
    return {
        "bucket": classified.bucket,
        "delivered_to": delivered,
        "reason": classified.reason,
    }
