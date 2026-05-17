"""Retro — the pipeline's backward pass, actor-wrapped.

Skeleton today: records that a pass was triggered, counts unprocessed
audit rows, marks them as processed. The actual compression
(read audit → extract patterns → write skill patches / memories)
lives in the /retro skill; this activity just shells out to it when
the audit-row count justifies a pass.

Audit/kick split:
  ~/.sweep/inbox/retro.jsonl   — retro's mailbox (kicks from metronome
                                  or operator)
  ~/.sweep/retro/audit.jsonl   — wait-bucket audit rows from pr-state
                                  and elsewhere (read by retro_cycle,
                                  not signaled into the actor)

The split keeps the inbox honest (one message = one unit of work) and
lets audit-row accumulation continue cheaply without waking the actor.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict
from pathlib import Path

from temporalio import activity

from sweep.types import Message


RETRO_INBOX = Path.home() / ".sweep" / "inbox" / "retro.jsonl"
HUMAN_INBOX = Path.home() / ".sweep" / "inbox" / "human.jsonl"
# Wait-bucket audits land in the inbox dir under a view-only name so
# they don't wake the retro actor. retro_cycle reads this on each pass.
AUDIT_PATH = Path.home() / ".sweep" / "inbox" / "retro_audit.jsonl"
PROCESSED_MARK = Path.home() / ".sweep" / "retro" / "last_processed.json"


def _count_unprocessed_audit() -> int:
    if not AUDIT_PATH.exists():
        return 0
    last_iso = ""
    if PROCESSED_MARK.exists():
        try:
            last_iso = json.loads(PROCESSED_MARK.read_text()).get("last_iso", "")
        except (json.JSONDecodeError, OSError):
            last_iso = ""
    count = 0
    for line in AUDIT_PATH.read_text().splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        row_ts = row.get("ts", "")
        if row_ts > last_iso:
            count += 1
    return count


def _mark_processed_now() -> None:
    PROCESSED_MARK.parent.mkdir(parents=True, exist_ok=True)
    PROCESSED_MARK.write_text(json.dumps({
        "last_iso": dt.datetime.now(dt.timezone.utc).isoformat(),
    }))


@activity.defn
async def kick_retro_card(sender: str = "metronome") -> str | None:
    """Deposit a retro card and signal retro-actor."""
    from sweep import observe
    from sweep.activities.pr_state import _signal_actor

    ts = dt.datetime.now(dt.timezone.utc)
    msg_id = f"retro-{ts.strftime('%Y%m%dT%H%M%S')}-{sender}"
    msg = Message(
        msg_id=msg_id,
        sender=sender,
        intent="pass",
        ts=ts.isoformat(),
    )
    RETRO_INBOX.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(RETRO_INBOX, "a") as f:
            f.write(json.dumps(asdict(msg)) + "\n")
    except Exception as e:
        observe.event("retro_card_write_failed",
                      error_type=type(e).__name__, error=str(e)[:200])
        return None
    observe.event("retro_card_deposited", sender=sender, msg_id=msg_id)
    return await _signal_actor("retro", msg)


def _emit_human_card(msg: Message, summary: dict) -> None:
    """Deposit one card on human.jsonl summarizing this retro pass.

    Every pass produces a card — even if everything was auto-fixed or
    nothing needed attention — because the operator's question is
    "what happened in the last window?" and a silent retro answers it
    badly. The card body distinguishes auto_fixes (applied without
    asking) from human_attended (need judgment).
    """
    ts = dt.datetime.now(dt.timezone.utc)
    out = Message(
        msg_id=f"human-from-{msg.msg_id}",
        sender="retro",
        intent="retro-summary",
        payload=summary,
        ts=ts.isoformat(),
        path=list(msg.path) + [msg.sender],
    )
    HUMAN_INBOX.parent.mkdir(parents=True, exist_ok=True)
    with open(HUMAN_INBOX, "a") as f:
        f.write(json.dumps(asdict(out)) + "\n")


@activity.defn
async def retro_cycle(msg: Message) -> dict:
    """Backward-pass stub. Counts unprocessed audit rows, records the
    pass, marks processed, surfaces a human card.

    Real behavior (next step, mirroring investigate_cycle's skill_runner
    pattern): shell out to the /retro skill, which reads the audit
    window, applies obvious fixes (skill patches, memory writes,
    parameter file edits) on its own, and reports what it could not
    decide. This stub records the trigger and emits a placeholder
    human card so the wiring is exercised end-to-end before the LLM
    invocation lands."""
    from sweep import observe

    unprocessed = _count_unprocessed_audit()
    observe.event(
        "retro_pass_triggered",
        sender=msg.sender,
        unprocessed_audit_rows=unprocessed,
        msg_id=msg.msg_id,
    )

    # Placeholder result shape — real /retro skill invocation will
    # populate auto_fixes and human_attended with concrete entries.
    summary = {
        "unprocessed_audit_rows": unprocessed,
        "auto_fixes": [],          # [{kind, path, what}]
        "human_attended": [],      # [{kind, summary, evidence_path}]
        "trigger_sender": msg.sender,
        "stub": True,              # remove once real /retro wiring lands
    }
    _emit_human_card(msg, summary)
    _mark_processed_now()
    return {
        "unprocessed_audit_rows": unprocessed,
        "human_card_emitted": True,
        "msg_id": msg.msg_id,
    }
