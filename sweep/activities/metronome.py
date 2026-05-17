"""Metronome — cadence schedule + tick activity.

Schedule lives in code so it ships with the worker; if a target needs
runtime tuning, externalize per-target to a ~/.sweep/control/<name>
file the same way rope's target works. Don't grow this dict into a
config format until two targets actually need different overrides.

Each tick reads ~/.sweep/metronome/last_fired.json for per-target
last-fired timestamps (durable across restart), kicks every target
that's due, and returns the seconds until the next-due entry so the
MetronomeActor can sleep that long.
"""

from __future__ import annotations

import datetime as dt
import json
from datetime import timedelta
from pathlib import Path

from temporalio import activity

from sweep.types import Message, forward_ledger


STATE_FILE = Path.home() / ".sweep" / "metronome" / "last_fired.json"


# (target_actor, cadence) — extensible. retro is first; future
# cadence-driven kicks land here without new workflow code.
SCHEDULE: list[tuple[str, timedelta]] = [
    ("retro", timedelta(hours=24)),
]


def _load_state() -> dict[str, str]:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(state: dict[str, str]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True))


async def _kick(target: str) -> None:
    """Dispatch to the target's kick_*_card helper. Per-target because
    each kicker has different required args (repo, sender, etc.); the
    metronome only knows about cadence, not target semantics."""
    from sweep import observe
    if target == "retro":
        from sweep.activities.retro import kick_retro_card
        await kick_retro_card(sender="metronome")
    else:
        observe.event("metronome_unknown_target", target=target)


@activity.defn
async def metronome_tick(manual: Message | None = None) -> dict:
    """Fire every due target; return seconds until next-due so the
    workflow can sleep that long.

    `manual`: present when an operator deposited a card on the
    metronome's inbox to force evaluation. Doesn't change due-logic;
    just lets the actor record who asked.
    """
    from sweep import observe

    state = _load_state()
    now = dt.datetime.now(dt.timezone.utc)
    fired: list[str] = []
    earliest_next: float | None = None

    for target, cadence in SCHEDULE:
        last_iso = state.get(target)
        if last_iso:
            try:
                last = dt.datetime.fromisoformat(last_iso)
            except ValueError:
                last = None
        else:
            last = None

        next_due = (last + cadence) if last else now
        if next_due <= now:
            try:
                await _kick(target)
                state[target] = now.isoformat()
                fired.append(target)
                # Next due is now + cadence
                target_next = (now + cadence - now).total_seconds()
            except Exception as e:
                observe.event(
                    "metronome_kick_failed", target=target,
                    error_type=type(e).__name__, error=str(e)[:200],
                )
                # Don't update last_fired on failure — retry next tick.
                target_next = 60.0
        else:
            target_next = (next_due - now).total_seconds()

        if earliest_next is None or target_next < earliest_next:
            earliest_next = target_next

    if fired:
        _save_state(state)

    observe.event(
        "metronome_tick",
        fired=fired,
        manual_msg_id=(manual.msg_id if manual else None),
        next_due_seconds=earliest_next,
    )
    return {
        "fired": fired,
        "next_due_seconds": earliest_next,
        "schedule_size": len(SCHEDULE),
    }


@activity.defn
async def kick_metronome_card(sender: str = "operator",
                              incoming: Message | None = None) -> str | None:
    """Operator or other-actor entry point: force a metronome evaluation
    pass right now (don't wait for the next scheduled wake)."""
    from sweep import observe
    from sweep.activities.pr_state import _signal_actor

    ts = dt.datetime.now(dt.timezone.utc)
    msg_id = f"metronome-{ts.strftime('%Y%m%dT%H%M%S')}-{sender}"
    msg = Message(
        msg_id=msg_id,
        sender=sender,
        intent="tick",
        ts=ts.isoformat(),
        ledger=forward_ledger(incoming),
    )
    INBOX = Path.home() / ".sweep" / "inbox" / "metronome.jsonl"
    INBOX.parent.mkdir(parents=True, exist_ok=True)
    from dataclasses import asdict
    try:
        with open(INBOX, "a") as f:
            f.write(json.dumps(asdict(msg)) + "\n")
    except Exception as e:
        observe.event("metronome_card_write_failed",
                      error_type=type(e).__name__, error=str(e)[:200])
        return None
    return await _signal_actor("metronome", msg)
