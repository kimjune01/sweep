"""Rope — pull-signal controller that regulates scout's inbox depth.

Idle signals from downstream actors (investigate, qa, sift) land in
rope.jsonl. Rope reads scout.jsonl depth and fires scout if it's below
the target. The signal is the trigger; the depth is the regulator.

This is a proportional controller, kanban-shaped: scout's inbox is the
process variable, rope is the controller, target is the setpoint. Below
target → fill; at-or-above target → drop the idle signal silently. The
line has fuel; downstream's idle isn't a request for more.

Why scout-depth alone (not aggregate WIP): every actor has its own WIP
cap at its inbox boundary, so the cap chain already bounds total
in-flight. Scout's inbox is the *only* thing rope can directly
influence (rope deposits there); ergo, regulate that and trust the
caps to do the rest.

Replaces:
  - leakdog's scout heartbeat (still kept as a slow bootstrap safety
    net — if rope itself gets stuck, leakdog's tick re-seeds the line)
  - triage_cycle's per-ack kick_scout_card (now routed through rope so
    all pull signals converge on one throttle point)

Tunable: ~/.sweep/control/rope_target (single integer, default 2).
Operator can `echo 3 > ~/.sweep/control/rope_target` to run the line
hotter; no code change, no restart.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict
from pathlib import Path

from temporalio import activity
from temporalio.exceptions import ApplicationError

from sweep.types import Message

ROPE_INBOX = Path.home() / ".sweep" / "inbox" / "rope.jsonl"
ROPE_TARGET_FILE = Path.home() / ".sweep" / "control" / "rope_target"
DEFAULT_TARGET = 2


def _read_target() -> int:
    """Read the depth setpoint from the control file. Operator-tunable.
    Falls back to DEFAULT_TARGET on any read/parse error so a malformed
    file doesn't wedge the controller."""
    try:
        return max(1, int(ROPE_TARGET_FILE.read_text().strip()))
    except Exception:
        return DEFAULT_TARGET


@activity.defn
async def kick_rope_card(sender: str = "idle") -> str | None:
    """Deposit an idle signal on rope.jsonl and signal rope-actor.

    Called by any actor that finds its own inbox empty after processing
    (a soft "I could take more work" hint). Rope decides whether the
    line actually needs more — the caller doesn't have to know about
    scout's depth or the target.
    """
    from sweep import observe
    from sweep.activities.pr_state import _signal_actor

    ts = dt.datetime.now(dt.timezone.utc)
    msg_id = f"rope-{ts.strftime('%Y%m%dT%H%M%S%f')}-{sender}"
    msg = Message(
        msg_id=msg_id,
        sender=sender,
        intent="pull",
        repo=None,
        pr=None,
        branch=None,
        payload={},
        ts=ts.isoformat(),
    )
    ROPE_INBOX.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(ROPE_INBOX, "a") as f:
            f.write(json.dumps(asdict(msg)) + "\n")
    except Exception as e:
        observe.event("rope_card_write_failed", sender=sender,
                      error_type=type(e).__name__, error=str(e)[:200])
        return None
    return await _signal_actor("rope", msg)


@activity.defn
async def rope_cycle(msg: Message) -> dict:
    """One controller tick. Read scout.jsonl depth, compare to target,
    fire scout if below. Drop the signal silently if at-or-above.

    No raise, no andon. Rope is the line's tempo regulator — if it
    fails, the line just doesn't pull, which is the safer failure mode.
    """
    from sweep import observe
    from sweep.inbox_state import inbox_states
    from sweep.activities.scout import kick_scout_card

    target = _read_target()
    try:
        s = inbox_states("scout")
        depth = len(s.get("queued", [])) + len(s.get("in_flight", []))
    except Exception as e:
        observe.event("rope_depth_read_failed",
                      error_type=type(e).__name__, error=str(e)[:200])
        return {"fired": False, "reason": "depth_read_failed"}

    if depth >= target:
        observe.event("rope_drop", depth=depth, target=target,
                      sender=msg.sender or "unknown")
        return {"fired": False, "depth": depth, "target": target,
                "reason": "above_target"}

    wf_id = await kick_scout_card(f"rope-{msg.sender or 'idle'}")
    observe.event("rope_fired", depth=depth, target=target,
                  sender=msg.sender or "unknown",
                  scout_wf=wf_id or "(no-signal)")
    return {"fired": True, "depth": depth, "target": target,
            "scout_wf": wf_id}
