"""GitHub API budget watchdog — three-tier jidoka for the core rate limit.

Tiers (projected core utilization at reset, with hysteresis):
  - ≥ 20% (_API_BUDGET_THRESHOLD): throttle — prospect-puller idles.
  - ≥ 50% (_API_BUDGET_ANDON):     andon  — marker written + line paused.
  - < 40% (_API_BUDGET_RECOVER):   recover — clear marker, lift pause.

The 10-point dead band between andon and recover prevents flap.

Originally lived in `sweep/activities/prospect.py`; extracted so both
the puller (check_pull_conditions) and leakdog daemon can import from
one place without dragging in prospect's full surface.

Per [[H21]], the auto-clear path runs from leakdog's independent tick,
not just the puller's loop — a wedged puller can't recover its own
andon. The clear function here is the shared mechanism; the daemon
calling it is what makes it survive wedge conditions.
"""

from __future__ import annotations

from pathlib import Path


# Prospect's share of the GitHub core rate limit. Conservative on
# purpose: pr-state polls every open PR on every cycle, drip does
# pushes, qa pulls reviews — they all share the same hourly bucket and
# their loads scale with the number of open PRs, not the operator's
# tempo. 20% leaves ~4000 calls/hr (5000 × 0.80) for everything
# downstream, which is the bottleneck under heavy roster. Bump this
# upward only after rate-limit hits stop appearing in andon.
_API_BUDGET_THRESHOLD = 0.20

# Projected utilization above this means the throttle failed: prospect
# (or something it sits in front of) is burning through the budget
# faster than the 20% cap allows. That's an andon — pull the cord,
# stop the line, demand operator eyes. Block AND record the marker.
_API_BUDGET_ANDON = 0.50

# Hysteresis: don't auto-resume the moment we drop under the andon
# threshold (we'd flap). Recovery happens once projected falls under
# this lower floor. 10-point dead band between andon and recover keeps
# the line from oscillating across the trigger.
_API_BUDGET_RECOVER = 0.40

_API_BUDGET_CACHE_S = 30        # how long to trust a rate_limit snapshot
_api_budget_cache: dict = {"ts": 0.0, "block_reason": None}


def _budget_andon_path() -> Path:
    return Path.home() / ".sweep" / "control" / "andon" / "prospect_puller.json"


def _record_budget_andon(reason: str) -> None:
    """Write an andon marker for prospect when the API budget goes
    critical. Inlines the file format from activities.worktree.record_andon
    so we don't need a workflow path to engage the cord."""
    import datetime as _dt
    import json as _json
    from sweep.control_state import set_paused
    path = _budget_andon_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "actor": "prospect_puller",
        "msg_id": "(api budget watchdog)",
        "reason": reason[:500],
        "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }
    path.write_text(_json.dumps(payload))
    set_paused(True)


def _clear_budget_andon_if_held() -> bool:
    """Auto-recover: if our budget-watchdog marker is the one holding
    the line, remove it and lift the pause (when no other markers
    remain). Returns True if a clear happened. Only touches our own
    marker — never clears anyone else's andon."""
    from sweep.control_state import set_paused
    path = _budget_andon_path()
    if not path.exists():
        return False
    path.unlink()
    andon_dir = Path.home() / ".sweep" / "control" / "andon"
    if not any(andon_dir.glob("*.json")):
        set_paused(False)
    return True


def _api_budget_block() -> str | None:
    """Return a block reason if projected core utilization at reset is
    over prospect's allotted share, else None. Cached for
    `_API_BUDGET_CACHE_S` to keep poll cycles cheap. The `gh api
    rate_limit` call itself doesn't count against the limit (per
    GitHub docs), so polling it is free.

    Cursor-safe: a `False` from this function makes the puller idle
    without invoking `prospect_one_pass`, so the stars cursor stays put."""
    import json as _json
    import subprocess as _sp
    import time as _time

    now = _time.time()
    if now - _api_budget_cache["ts"] < _API_BUDGET_CACHE_S:
        return _api_budget_cache["block_reason"]

    reason: str | None = None
    try:
        raw = _sp.run(
            ["gh", "api", "rate_limit"],
            capture_output=True, text=True, timeout=3,
        )
        if raw.returncode == 0:
            core = _json.loads(raw.stdout).get("resources", {}).get("core", {})
            used = core.get("used", 0)
            limit = core.get("limit", 0)
            reset = core.get("reset", 0)
            if limit:
                secs_remaining = max(1, int(reset - now))
                elapsed = 3600 - secs_remaining
                # Need at least 60s of history before extrapolating —
                # otherwise a single early request looks catastrophic.
                if elapsed >= 60:
                    projected = used * 3600 / elapsed
                    proj_pct = projected / limit
                    # Auto-clear runs FIRST so it can fire even while
                    # the throttle block is still engaged (the throttle
                    # band 20-40% needs to be able to release a prior
                    # andon — otherwise we'd be latched until we drop
                    # under 20%, defeating the hysteresis).
                    if proj_pct < _API_BUDGET_RECOVER:
                        _clear_budget_andon_if_held()
                    if proj_pct >= _API_BUDGET_ANDON:
                        reason = (f"api budget CRITICAL "
                                  f"({100 * proj_pct:.0f}% projected ≥ "
                                  f"{int(_API_BUDGET_ANDON * 100)}% andon threshold)")
                        _record_budget_andon(reason)
                    elif proj_pct >= _API_BUDGET_THRESHOLD:
                        reason = (f"api budget tight "
                                  f"({100 * proj_pct:.0f}% projected, "
                                  f"prospect capped at {int(_API_BUDGET_THRESHOLD * 100)}%)")
    except Exception:
        pass

    _api_budget_cache["ts"] = now
    _api_budget_cache["block_reason"] = reason
    return reason
