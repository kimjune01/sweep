"""Heart — periodic heartbeat actor + deliberate-chaos cell.

Fires on the metronome's cadence and writes one line of "the line is
alive" telemetry per beat. Cheap by design: no LLM, no per-repo work,
no subprocess. The point is to leave a visible trail in the worklog
so an external observer (cockpit, monitoring script, the operator
glancing at events) can tell "the substrate is up" without having to
inspect actor depths.

Heart is also the substrate's chaos cell: with a small per-beat
probability (default 5%), the activity raises non-retryable on
purpose. That trips heart-actor's andon — exercising the recovery
path regularly proves the andon/clear/drain machinery still works
instead of letting it rot until a real failure surfaces a latent bug.
Cheap to inhabit (other actors don't care), visible to the operator,
and recovery is one command (`sweep andon clear heart_cycle`).

Tune via ~/.sweep/control/heart_chaos_rate (float 0.0–1.0). Set to 0
to disable; set to 1 to fail every beat (useful when debugging the
andon path itself).

Future jobs that fit here:
  - rotate stale state files
  - emit a "still here" line for each long-running activity
  - kick `leakdog` on its own cadence if we ever decouple
"""

from __future__ import annotations

import datetime as dt
import json
import random
from dataclasses import asdict
from pathlib import Path

from temporalio import activity
from temporalio.exceptions import ApplicationError

from sweep.types import Message, forward_ledger


HEART_INBOX = Path.home() / ".sweep" / "inbox" / "heart.jsonl"
HEART_LOG = Path.home() / ".sweep" / "sweep-log" / "heart.jsonl"
CHAOS_RATE_PATH = Path.home() / ".sweep" / "control" / "heart_chaos_rate"
_DEFAULT_CHAOS_RATE = 0.05  # ~1 in 20 beats fail, ~1 forced andon per 5h


def _chaos_rate() -> float:
    try:
        v = float(CHAOS_RATE_PATH.read_text().strip())
    except (OSError, ValueError):
        return _DEFAULT_CHAOS_RATE
    return max(0.0, min(1.0, v))


def _append(inbox: Path, msg: Message) -> None:
    inbox.parent.mkdir(parents=True, exist_ok=True)
    with open(inbox, "a") as f:
        f.write(json.dumps(asdict(msg)) + "\n")


@activity.defn
async def kick_heart_card(sender: str = "metronome",
                          incoming: Message | None = None) -> str | None:
    """Deposit a heart card on heart.jsonl and signal heart-actor."""
    from sweep import observe
    from sweep.activities.pr_state import _signal_actor

    ts = dt.datetime.now(dt.timezone.utc)
    msg_id = f"heart-{ts.strftime('%Y%m%dT%H%M%S')}"
    msg = Message(
        msg_id=msg_id, sender=sender, intent="heartbeat",
        repo=None, pr=None, branch=None,
        payload={}, ts=ts.isoformat(),
        ledger=forward_ledger(incoming),
    )
    try:
        _append(HEART_INBOX, msg)
    except Exception as e:
        observe.event("heart_card_write_failed",
                      error_type=type(e).__name__, error=str(e)[:200])
        return None
    observe.event("heart_card_deposited", sender=sender, msg_id=msg_id)
    return await _signal_actor("heart", msg)


@activity.defn
async def heart_cycle(msg: Message) -> dict:
    """One heartbeat. Writes a line to ~/.sweep/sweep-log/heart.jsonl
    with the tick's timestamp + sender. The file is the source of
    truth — anyone curious whether the line is alive tails it.
    """
    from sweep import observe

    ts = dt.datetime.now(dt.timezone.utc)

    # Chaos cell: per-beat probability of deliberate andon. Exercises
    # the recovery path so a real failure doesn't surface a latent bug
    # the first time the path runs in months.
    rate = _chaos_rate()
    if rate > 0 and random.random() < rate:
        observe.event("heart_chaos_triggered", rate=rate,
                      sender=msg.sender, msg_id=msg.msg_id)
        raise ApplicationError(
            f"chaos: deliberate heart failure to prove andon path "
            f"(rate={rate}). Recover with `sweep andon clear heart_cycle`.",
            non_retryable=True,
        )

    line = {
        "ts": ts.isoformat(),
        "sender": msg.sender,
        "msg_id": msg.msg_id,
    }
    HEART_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(HEART_LOG, "a") as f:
        f.write(json.dumps(line) + "\n")
    observe.event("heart_beat", sender=msg.sender, msg_id=msg.msg_id)
    return {"ok": True, "ts": ts.isoformat()}
