"""Compose — PR message writer between qa and submit.

Sits in the production lane after qa converges with verdict=pass and a
fix, before submit's pre-publish gate. Single job: write the PR title +
body that gives the fix its best shot at maintainer acceptance.

Why not investigate or qa: investigate's fix can be wrong (qa rejects
or revises), and qa rejects/revises in place — neither can guarantee
the code is final at the moment the message gets written. Message
composition must consume the *verified* code, which means it runs
strictly after qa.

Why not submit: composition is creative (one shot at convincing a
maintainer), validation is mechanical (length, no em-dashes, no LLM
tics). They don't belong in the same actor. Submit validates compose's
output without writing.

Why a separate actor at all: PR-message-writing is half the value of
non-trivial PRs. Burying it as a side-effect of /drip --push (the old
behavior) hid a load-bearing responsibility. First-class actor makes
the responsibility visible and replaceable.

Skeleton: passes the card through to submit without invoking a writer
skill yet. The /drip skill's inline message-writing still fires
downstream until /compose is built. When /compose lands, compose_cycle
calls it and writes the result into the attestation; submit validates;
respond pushes with the prepared message.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict
from pathlib import Path

from temporalio import activity
from temporalio.exceptions import ApplicationError

from sweep.types import Message, forward_ledger

COMPOSE_INBOX = Path.home() / ".sweep" / "inbox" / "compose.jsonl"


@activity.defn
async def kick_compose_card(repo: str, branch: str, pr: int | None = None,
                            sender: str = "qa",
                            attestation_hash: str | None = None,
                            incoming: Message | None = None) -> str | None:
    """Deposit a verified-fix card on compose.jsonl and signal
    compose-actor. Called by qa when verdict=pass and a fix is ready
    to be packaged for the maintainer.

    Compose then writes the PR text and hands off to submit for the
    final-bastion gate."""
    from sweep import observe
    from sweep.activities.pr_state import _signal_actor

    ts = dt.datetime.now(dt.timezone.utc)
    slug = repo.replace("/", "-")
    pr_part = pr if pr is not None else "new"
    msg_id = f"compose-{ts.strftime('%Y%m%dT%H%M%S')}-{slug}-{pr_part}"
    payload = {}
    if attestation_hash:
        payload["attestation_hash"] = attestation_hash
    msg = Message(
        msg_id=msg_id,
        sender=sender,
        intent="compose",
        repo=repo,
        pr=pr,
        branch=branch,
        payload=payload,
        ts=ts.isoformat(),
        ledger=forward_ledger(incoming),
    )
    COMPOSE_INBOX.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(COMPOSE_INBOX, "a") as f:
            f.write(json.dumps(asdict(msg)) + "\n")
    except Exception as e:
        observe.event("compose_card_write_failed", repo=repo, branch=branch,
                      error_type=type(e).__name__, error=str(e)[:200])
        return None
    observe.event("compose_card_deposited", repo=repo, branch=branch,
                  pr=pr, sender=sender, msg_id=msg_id)
    return await _signal_actor("compose", msg)


@activity.defn
async def compose_cycle(msg: Message) -> dict:
    """Write the PR message and hand off to submit.

    Skeleton: passes through without invoking a writer skill. Once a
    /compose skill exists, this activity calls it, validates the output
    isn't empty, and writes title+body into msg.payload['pr_title'] and
    msg.payload['pr_body'] before kicking submit.

    For now, submit runs with no message — /drip --push downstream writes
    one inline (today's behavior). The actor exists so the topology is
    honest; the skill upgrade lands separately.
    """
    if not msg.repo or not msg.branch:
        raise ApplicationError("compose: repo + branch required",
                               non_retryable=True)
    from sweep import observe
    from sweep.activities.submit import kick_submit_card

    attestation_hash = (msg.payload or {}).get("attestation_hash")
    wf_id = await kick_submit_card(
        msg.repo, msg.branch, msg.pr,
        sender="compose",
        attestation_hash=attestation_hash,
        incoming=msg,
    )
    observe.event("compose_passed_through", repo=msg.repo, branch=msg.branch,
                  pr=msg.pr, msg_id=msg.msg_id,
                  submit_wf=wf_id or "(no-signal)")
    return {"composed": False, "passthrough": True, "kicked_submit": wf_id}
