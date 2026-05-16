"""Per-actor API budget tracking with per-actor andon.

Each actor declares a max share of the GitHub core rate limit. Calls
made under the actor's context get counted against its hourly budget.
When usage exceeds (share + overshoot), the actor's own andon fires —
the marker names the actor responsible, giving the operator higher-
resolution diagnosis than a generic "API tight."

Tracking mechanism:
- `contextvars.ContextVar` set at activity entry via `as_caller(name)`.
- `gh_io._gh` reads the var and calls `budget.record(1)` on each
  successful subprocess call.
- A 1-hour sliding window of per-call timestamps in
  `~/.sweep/budget/<actor>.jsonl` is the source of truth for usage.

Limitations:
- Subprocess-based skills (`/triage`, `/drip`, `/investigate`, `/qa`)
  shell out to `gh` directly, NOT through our gh_io wrapper. Those
  calls are invisible to this tracker. They're tracked at the
  activity-invocation level (one estimated cost per activity run),
  which is rough but better than nothing.
- The hour window is rolling per-call, not aligned to GitHub's
  rate-limit reset. The two windows can drift up to 60 min apart.
  Acceptable: per-actor share is about fairness across actors, not
  about hugging GitHub's exact reset clock.
"""

from __future__ import annotations

import contextvars
import datetime as dt
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sweep.io_safe import atomic_write_text


BUDGET_DIR = Path.home() / ".sweep" / "budget"
HOURLY_LIMIT = 5000  # gh core rate limit
OVERSHOOT = 0.10     # actor andons when usage exceeds share by this much

# Per-actor share of the hourly limit. Sum > 1.0 by design — these are
# caps, not reservations; one actor's slack doesn't pass to others.
SHARES: dict[str, float] = {
    "pr-state":      0.40,
    "prospect":      0.20,
    "qa":            0.15,
    "investigate":   0.15,
    "notifications": 0.10,
    "drip":          0.10,
}

# Estimated cost-per-invocation for subprocess actors that bypass
# gh_io. Used by `record_subprocess_estimate(...)` so we still get
# coarse attribution for the skills.
SUBPROCESS_ESTIMATE: dict[str, int] = {
    "triage":      5,    # /triage typically: search + a few views
    "investigate": 30,   # /investigate fans out; expensive
    "drip":        10,   # /drip pushes + checks
    "qa":          8,    # /qa pulls reviews + checks
}

# Caller context — set by each actor at entry, read by gh_io on each
# subprocess call. Default "" so calls from places we forgot to tag
# get attributed to "unknown" (which counts against no share, so
# they never trip the actor andon — they DO show up in `unknown.jsonl`
# so leakdog can flag the gap).
_caller: contextvars.ContextVar[str] = contextvars.ContextVar(
    "budget_caller", default="",
)


@contextmanager
def as_caller(actor: str) -> Iterator[None]:
    """Set the caller context for the wrapped block. gh_io calls
    inside attribute their cost to this actor."""
    token = _caller.set(actor)
    try:
        yield
    finally:
        _caller.reset(token)


def current_caller() -> str:
    return _caller.get() or "unknown"


def set_caller(actor: str) -> None:
    """Set the caller for the rest of this asyncio task. Use at activity
    entry when wrapping the whole body in `with as_caller(...):` would
    require deep indenting. The contextvar lives for the task's lifetime
    and goes away with it."""
    _caller.set(actor)


def record(n: int = 1, caller: str | None = None) -> None:
    """Append n timestamps to the current (or named) actor's hourly log."""
    actor = caller or current_caller()
    if not actor:
        return
    BUDGET_DIR.mkdir(parents=True, exist_ok=True)
    p = BUDGET_DIR / f"{actor}.jsonl"
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
    try:
        with open(p, "a") as f:
            for _ in range(n):
                f.write(now_iso + "\n")
    except OSError:
        pass


def record_subprocess_estimate(actor: str) -> None:
    """Bump the actor's counter by its estimated per-invocation cost.
    Used by skill-shelling activities (triage/drip/investigate/qa)
    where we can't see the real gh calls inside the subprocess."""
    n = SUBPROCESS_ESTIMATE.get(actor, 5)
    record(n, caller=actor)


def calls_last_hour(actor: str) -> int:
    """Count records in the actor's log from the last hour. Prunes
    older entries opportunistically when >50% of the file is stale."""
    p = BUDGET_DIR / f"{actor}.jsonl"
    if not p.exists():
        return 0
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
    fresh: list[str] = []
    total = 0
    try:
        text = p.read_text()
    except OSError:
        return 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        total += 1
        try:
            t = dt.datetime.fromisoformat(line)
        except ValueError:
            continue
        if t >= cutoff:
            fresh.append(line)
    if total and len(fresh) < total / 2:
        try:
            atomic_write_text(p, "\n".join(fresh) + ("\n" if fresh else ""))
        except OSError:
            pass
    return len(fresh)


def share_used(actor: str) -> float:
    """Actor's usage as a fraction of its allotted share. 1.0 = at cap;
    >1.0 = over cap; >=1.0+OVERSHOOT = andon-worthy."""
    share = SHARES.get(actor, 0.0)
    if share <= 0:
        return 0.0
    cap_calls = HOURLY_LIMIT * share
    return calls_last_hour(actor) / cap_calls if cap_calls else 0.0


# ---- per-actor andon markers (mirror prospect's pattern) ---------
ANDON_DIR = Path.home() / ".sweep" / "control" / "andon"


def _andon_path(actor: str) -> Path:
    return ANDON_DIR / f"budget_{actor}.json"


def record_andon(actor: str, reason: str) -> None:
    """Write a per-actor budget andon marker and pause the line."""
    from sweep.control_state import set_paused
    ANDON_DIR.mkdir(parents=True, exist_ok=True)
    p = _andon_path(actor)
    payload = {
        "actor": f"budget_{actor}",
        "msg_id": f"(budget watchdog: {actor})",
        "reason": reason[:500],
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    p.write_text(json.dumps(payload))
    set_paused(True)


def clear_andon_if_held(actor: str) -> bool:
    """Remove this actor's budget andon if held; lift pause when no
    markers remain. Leakdog calls this when the actor drops back to
    safe range (currently: under its share, no overshoot needed —
    auto-recover hysteresis = share itself)."""
    from sweep.control_state import set_paused
    p = _andon_path(actor)
    if not p.exists():
        return False
    p.unlink()
    if not any(ANDON_DIR.glob("*.json")):
        set_paused(False)
    return True


def check_and_andon(actor: str) -> str | None:
    """Returns a block reason if the actor is over its share. Fires
    the andon (and pauses) when overshoot is exceeded. Use as the
    gate before an actor's main work."""
    if actor not in SHARES:
        return None
    used = share_used(actor)
    share = SHARES[actor]
    if used >= 1.0 + OVERSHOOT:
        reason = (f"{actor} over budget — {100*used:.0f}% of its "
                  f"{int(share*100)}% share (andon at "
                  f"+{int(OVERSHOOT*100)} overshoot)")
        record_andon(actor, reason)
        return reason
    if used >= 1.0:
        return (f"{actor} at cap — {100*used:.0f}% of its "
                f"{int(share*100)}% share (throttle, no andon)")
    return None


def is_blocked(actor: str) -> bool:
    """Cheap: is the actor's own budget andon marker present?"""
    return _andon_path(actor).exists()


def all_actor_status() -> list[dict]:
    """For diagnostics — return per-actor (actor, calls, share, used%)."""
    out = []
    for actor, share in SHARES.items():
        used = share_used(actor)
        out.append({
            "actor": actor,
            "calls_1h": calls_last_hour(actor),
            "share": share,
            "share_used_pct": round(100 * used, 1),
            "over_cap": used >= 1.0,
            "andon_pulled": is_blocked(actor),
        })
    # Untagged "unknown" bucket — calls that escaped attribution.
    unknown = calls_last_hour("unknown")
    if unknown:
        out.append({
            "actor": "unknown",
            "calls_1h": unknown,
            "share": None,
            "share_used_pct": None,
            "over_cap": False,
            "andon_pulled": False,
        })
    return out
