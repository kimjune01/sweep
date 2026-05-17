"""Respond — push verbs (rebase, publish, close).

The `respond_cycle` activity itself lives in `skill_runner.py` (it
shells out to /drip --push or --check). This module provides the
`kick_respond_card` helper so upstream actors can deposit
push-shaped cards on respond.jsonl without knowing the routing
layer's internal _signal_actor mechanics.

Called by:
  - reqa-actor on verdict=pass for engagement-lane patches (push to
    existing branch)
  - submit-actor (when wired) for production-lane new PRs

Historical: respond.jsonl was previously fed only by remit's bucket
routing (CHANGES_REQUESTED → respond for auto-rebase/close). This
helper extends the same inbox for actor-to-actor handoffs.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict
from pathlib import Path

from temporalio import activity

from sweep.types import Message, forward_ledger


RESPOND_INBOX = Path.home() / ".sweep" / "inbox" / "respond.jsonl"


@activity.defn
async def kick_respond_card(repo: str, branch: str,
                            pr: int | None = None,
                            sender: str = "qa",
                            intent: str = "publish",
                            attestation_hash: str | None = None,
                            incoming: Message | None = None) -> str | None:
    """Deposit a publish/rebase/close card on respond.jsonl and signal
    respond-actor. Returns the workflow id on success, None on failure."""
    from sweep import observe
    from sweep.activities.pr_state import _signal_actor

    ts = dt.datetime.now(dt.timezone.utc)
    slug = repo.replace("/", "-")
    pr_part = pr if pr is not None else "new"
    msg_id = f"respond-{ts.strftime('%Y%m%dT%H%M%S')}-{slug}-{pr_part}-{intent}"
    payload: dict = {}
    if attestation_hash:
        payload["attestation_hash"] = attestation_hash
    msg = Message(
        msg_id=msg_id,
        sender=sender,
        intent=intent,
        repo=repo,
        pr=pr,
        branch=branch,
        payload=payload,
        ts=ts.isoformat(),
        ledger=forward_ledger(incoming),
    )
    RESPOND_INBOX.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(RESPOND_INBOX, "a") as f:
            f.write(json.dumps(asdict(msg)) + "\n")
    except Exception as e:
        observe.event("respond_card_write_failed", repo=repo, pr=pr,
                      error_type=type(e).__name__, error=str(e)[:200])
        return None
    observe.event("respond_card_deposited", repo=repo, pr=pr,
                  sender=sender, intent=intent, msg_id=msg_id)
    return await _signal_actor("respond", msg)
