"""Rope — pull-signal controller that regulates scout's inbox depth.

Idle signals from downstream actors (investigate, qa, sift) land in
rope.jsonl. Rope reads scout.jsonl depth and fires scout if it's below
the target. The signal is the trigger; the depth is the regulator.

This is a proportional controller, kanban-shaped: scout's inbox is the
process variable, rope is the controller, target is the setpoint. Below
target → fill; at-or-above target → drop the idle signal silently. The
line has fuel; downstream's idle isn't a request for more.

Why scout + triage depth (not just scout): triage is the LLM-cost
choke point right downstream of scout/sift. If triage is already
backed up, firing more scout cards just grows the queue without
moving work. Reading triage's depth lets rope back off when the
bottleneck is downstream, not at scout itself.

Both inboxes gated by the same target: rope fires only if scout AND
triage both have headroom. Either being at/above target means
backpressure; rope drops the idle signal.

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

from sweep.types import Message, forward_ledger

ROPE_INBOX = Path.home() / ".sweep" / "inbox" / "rope.jsonl"
ROPE_TARGET_FILE = Path.home() / ".sweep" / "control" / "rope_target"
ROPE_COOLDOWN_FILE = Path.home() / ".sweep" / "control" / "rope_cooldown"
ROPE_LAST_FIRED_FILE = Path.home() / ".sweep" / "state" / "rope_last_fired"
DEFAULT_TARGET = 2
DEFAULT_COOLDOWN_S = 60


def _read_target() -> int:
    """Read the depth setpoint from the control file. Operator-tunable.
    Falls back to DEFAULT_TARGET on any read/parse error so a malformed
    file doesn't wedge the controller."""
    try:
        return max(1, int(ROPE_TARGET_FILE.read_text().strip()))
    except Exception:
        return DEFAULT_TARGET


def _read_cooldown_s() -> int:
    """Cooldown window between rope fires. Mitigates lag-induced
    thrashing: triage depth lags scout fires by the scout→sift→triage
    cascade time, so without a cooldown, rope keeps tugging in the
    blind period and overshoots when the cascade lands. Default 60s
    matches the longest healthy propagation."""
    try:
        return max(0, int(ROPE_COOLDOWN_FILE.read_text().strip()))
    except Exception:
        return DEFAULT_COOLDOWN_S


def _last_fired_ts() -> float:
    """Unix timestamp of the last rope_fired, 0.0 if never. Disk-backed
    so it survives worker restarts — a restart shouldn't reset the
    cooldown clock."""
    try:
        return float(ROPE_LAST_FIRED_FILE.read_text().strip())
    except Exception:
        return 0.0


def _record_fire(ts: float) -> None:
    """Write the last-fired timestamp. Best-effort — if the write
    fails, the next cycle's cooldown check falls back to 0.0 and we
    might over-fire once; preferable to raising and wedging the
    controller."""
    try:
        ROPE_LAST_FIRED_FILE.parent.mkdir(parents=True, exist_ok=True)
        ROPE_LAST_FIRED_FILE.write_text(f"{ts:.3f}")
    except Exception:
        pass


@activity.defn
async def kick_rope_card(sender: str = "idle",
                         incoming: Message | None = None) -> str | None:
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
        repo="",
        pr=None,
        branch=None,
        payload={},
        ts=ts.isoformat(),
        ledger=forward_ledger(incoming),
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
    import time
    from sweep import observe
    from sweep.inbox_state import inbox_states
    from sweep.activities.scout import kick_scout_card

    target = _read_target()
    cooldown_s = _read_cooldown_s()
    now = time.time()
    elapsed = now - _last_fired_ts()
    if elapsed < cooldown_s:
        observe.event("rope_cooldown",
                      elapsed_s=round(elapsed, 1),
                      cooldown_s=cooldown_s,
                      sender=msg.sender or "unknown")
        return {"fired": False, "reason": "cooldown",
                "elapsed_s": round(elapsed, 1),
                "cooldown_s": cooldown_s}

    def _depth(actor: str) -> int:
        try:
            s = inbox_states(actor)
            return len(s.get("queued", [])) + len(s.get("in_flight", []))
        except Exception:
            return -1  # treat read failures as "unknown"; fall through to drop

    scout_d = _depth("scout")
    triage_d = _depth("triaged")
    if scout_d < 0 or triage_d < 0:
        observe.event("rope_depth_read_failed",
                      scout=scout_d, triage=triage_d)
        return {"fired": False, "reason": "depth_read_failed"}

    if scout_d >= target or triage_d >= target:
        observe.event("rope_drop",
                      scout_depth=scout_d, triage_depth=triage_d,
                      target=target, sender=msg.sender or "unknown")
        return {"fired": False, "scout_depth": scout_d,
                "triage_depth": triage_d, "target": target,
                "reason": "above_target"}

    wf_id = await kick_scout_card(f"rope-{msg.sender or 'idle'}", incoming=msg)
    _record_fire(now)
    observe.event("rope_fired",
                  scout_depth=scout_d, triage_depth=triage_d,
                  target=target, cooldown_s=cooldown_s,
                  sender=msg.sender or "unknown",
                  scout_wf=wf_id or "(no-signal)")
    return {"fired": True, "scout_depth": scout_d,
            "triage_depth": triage_d, "target": target,
            "scout_wf": wf_id}
