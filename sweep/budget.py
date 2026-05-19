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
HOURLY_LIMIT = 5000  # gh core rate limit (GitHub-side window = 1h)
OVERSHOOT = 0.10     # actor andons when usage exceeds share by this much

# Per-actor measurement window. GitHub's rate-limit window is 1h, but
# the actor andon uses a tighter window so bursts trip faster and
# recoveries clear faster. The cap is pro-rated to the same fraction:
# a 15min window means cap_calls = HOURLY_LIMIT * share * (15/60).
# Same share semantics; just a higher-resolution lens.
LOCAL_WINDOW_MINUTES = 15

# Per-actor share of the hourly limit. Sum > 1.0 by design — these are
# caps, not reservations; one actor's slack doesn't pass to others.
SHARES: dict[str, float] = {
    # Notifications auto-runs every 60s and is the real PR querier in
    # steady state. `remit` covers leakdog's periodic full-scan seeder
    # (`_seed_unclassified_prs`) — formerly the `pr-state` escape-hatch
    # share, retired with the CLI in favor of the autonomous tick.
    "notifications": 0.25,
    "sift":          0.18,   # per-issue cycle: cached meta + sometimes issue_events
    "scout":         0.02,   # one search per cycle, alternating sources
    "qa":            0.15,
    # investigate + reinvestigate bumped +10pp each on 2026-05-18 after
    # the context pack landed. The old 15/10 caps were sized for the
    # opus fan-out era when every cycle was ~30 invisible-subprocess
    # gh calls; with the pack the actual call count is closer to 6-8
    # but the SUBPROCESS_ESTIMATE stayed at 30 (conservative until we
    # have real measurements). Bumping the share so the estimate's
    # conservatism doesn't false-andon every burst.
    "investigate":   0.25,
    # reinvestigate gets its own share (separate from investigate)
    # because engagement-lane demand is reactive — a bulk CI-failing
    # storm can drown new-bug investigation if they share a budget.
    # Lower than investigate's because most engagement-lane work
    # is rote (reqa/respond handle the mechanical fixes; reinvestigate
    # is the harder case that recurs less often per repo).
    "reinvestigate": 0.20,
    "respond":       0.10,
    "remit":         0.10,
}

# Estimated cost-per-invocation for subprocess actors that bypass
# gh_io. Used by `record_subprocess_estimate(...)` so we still get
# coarse attribution for the skills.
SUBPROCESS_ESTIMATE: dict[str, int] = {
    "triage":      5,    # /triage typically: search + a few views
    "investigate": 30,   # /investigate fans out; expensive
    # reinvestigate uses the same /investigate skill but routes
    # against its own budget key (above). Same per-invocation cost.
    "reinvestigate": 30,
    "respond":     10,   # /drip pushes + checks (respond-actor wraps the skill)
    "qa":          8,    # /qa pulls reviews + checks
}


# Per-actor self-throttle caps: max card completions per LOCAL_WINDOW.
# Distinct from the SHARES-derived ops budget — that's "calls against
# the GitHub rate limit"; this is "operator-paced flow control on
# expensive skills." Cap is in card-completion units (counted from
# events.jsonl) so it's robust to per-card op variance.
#
# To add a throttle: pick the actor key + the event-kind(s) emitted
# at completion + the cap.
THROTTLE_CAPS: dict[str, tuple[tuple[str, ...], int]] = {
    # (kept for actors that want completion-rate control; reinvestigate
    # moved to WIP_CAPS below — concurrent-instances semantics is what
    # Little's-Law-style flow control actually wants.)
}


# Per-actor WIP caps: max in_flight instances at any moment. Differs
# from THROTTLE_CAPS in semantics: rate vs. parallelism. WIP cap is
# the right shape for "don't let reinvestigate spawn N concurrent
# Claude subprocesses" — once 2 are running, a third has to wait for
# one to finish, regardless of how fast they finish.
#
# Read from inbox_state — the durable started/acked ledgers are the
# ground truth for what's in flight right now.
WIP_CAPS: dict[str, int] = {
    "reinvestigate": 2,  # at most 2 concurrent investigations open
}


def is_throttled(actor: str, *, minutes: int = LOCAL_WINDOW_MINUTES) -> bool:
    """Return True if `actor` should idle. Two semantically distinct
    throttles, checked in order:

      1. WIP_CAPS[actor]: max concurrent in_flight cards. Reads
         inbox_state's `in_flight` partition (started-but-not-acked
         msg_ids). At-or-above the cap → idle until one finishes.
      2. THROTTLE_CAPS[actor]: max completions in the local window.
         Reads events.jsonl for the configured completion-kind events.

    Fail-open: any error returns False so a broken throttle doesn't
    strand the actor."""
    wip_cap = WIP_CAPS.get(actor)
    if wip_cap is not None:
        try:
            from sweep.inbox_state import inbox_states
            s = inbox_states(actor)
            in_flight = len(s.get("in_flight", []))
            if in_flight >= wip_cap:
                return True
        except Exception:
            pass  # fail-open

    cfg = THROTTLE_CAPS.get(actor)
    if cfg is None:
        return False
    completion_kinds, cap = cfg
    events_path = Path.home() / ".sweep" / "events.jsonl"
    if not events_path.exists():
        return False
    now = dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(minutes=minutes)
    count = 0
    try:
        # Tail the file — only recent events matter. ~10K lines is
        # cheap to walk in Python and well-covers the local window.
        text = events_path.read_text()
        lines = text.splitlines()[-10000:]
        for line in lines:
            if not line.strip():
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("kind") not in completion_kinds:
                continue
            ts_s = e.get("ts", "")
            try:
                ts = dt.datetime.fromisoformat(ts_s)
            except ValueError:
                continue
            if ts >= cutoff:
                count += 1
                if count >= cap:
                    return True
    except OSError:
        return False
    return False

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


def calls_last_window(actor: str, *, minutes: int = LOCAL_WINDOW_MINUTES) -> int:
    """Count records in the actor's log from the last `minutes`. Prunes
    entries older than 1h (GitHub's hard window) opportunistically when
    >50% of the file is stale — keeps the file from growing unbounded
    even when the read window is shorter."""
    p = BUDGET_DIR / f"{actor}.jsonl"
    if not p.exists():
        return 0
    now = dt.datetime.now(dt.timezone.utc)
    read_cutoff = now - dt.timedelta(minutes=minutes)
    prune_cutoff = now - dt.timedelta(hours=1)
    in_window = 0
    keep: list[str] = []
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
        if t >= prune_cutoff:
            keep.append(line)
        if t >= read_cutoff:
            in_window += 1
    if total and len(keep) < total / 2:
        try:
            atomic_write_text(p, "\n".join(keep) + ("\n" if keep else ""))
        except OSError:
            pass
    return in_window


def share_used(actor: str) -> float:
    """Actor's usage as a fraction of its allotted share over the local
    measurement window. 1.0 = at cap; >1.0 = over cap; >=1.0+OVERSHOOT
    = andon-worthy. Cap is pro-rated: HOURLY_LIMIT × share × (window/60)."""
    share = SHARES.get(actor, 0.0)
    if share <= 0:
        return 0.0
    cap_calls = HOURLY_LIMIT * share * (LOCAL_WINDOW_MINUTES / 60.0)
    return calls_last_window(actor) / cap_calls if cap_calls else 0.0


# ---- per-actor andon markers (mirror sift's pattern) ---------
ANDON_DIR = Path.home() / ".sweep" / "control" / "andon"


def _andon_path(actor: str) -> Path:
    return ANDON_DIR / f"budget_{actor}.json"


def record_andon(actor: str, reason: str) -> None:
    """Write a per-actor budget andon marker and pause the line."""
    from sweep.control_state import set_paused
    from sweep import observe
    ANDON_DIR.mkdir(parents=True, exist_ok=True)
    p = _andon_path(actor)
    actor_name = f"budget_{actor}"
    payload = {
        "actor": actor_name,
        "msg_id": f"(budget watchdog: {actor})",
        "reason": reason[:500],
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    p.write_text(json.dumps(payload))
    set_paused(True)
    # Stoppage instrumentation — wasteboard's uptime panel pairs this
    # with andon_cleared to compute downtime. Watchdog-style andons
    # were invisible to that panel before this event fired (the panel
    # showed 100% uptime while a marker was live — caught 2026-05-18).
    observe.event("andon_recorded", actor=actor_name,
                  msg_id=payload["msg_id"], reason=reason[:200],
                  ts=payload["ts"])


def clear_andon_if_held(actor: str) -> bool:
    """Remove this actor's budget andon if held; lift pause when no
    markers remain. Leakdog calls this when the actor drops back to
    safe range (currently: under its share, no overshoot needed —
    auto-recover hysteresis = share itself)."""
    from sweep.control_state import set_paused
    from sweep import observe
    p = _andon_path(actor)
    if not p.exists():
        return False
    p.unlink()
    if not any(ANDON_DIR.glob("*.json")):
        set_paused(False)
    observe.event("andon_cleared", actor=f"budget_{actor}")
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
                  f"{int(share*100)}% share in {LOCAL_WINDOW_MINUTES}m "
                  f"(andon at +{int(OVERSHOOT*100)} overshoot)")
        record_andon(actor, reason)
        return reason
    if used >= 1.0:
        return (f"{actor} at cap — {100*used:.0f}% of its "
                f"{int(share*100)}% share in {LOCAL_WINDOW_MINUTES}m "
                f"(throttle, no andon)")
    return None


def is_blocked(actor: str) -> bool:
    """Budget andons are GLOBAL — any actor's budget overshoot halts the
    whole line. The per-actor marker file (_andon_path) is just the
    diagnostic trail naming which actor tripped it; the gate is global
    pause state. Witnessed: sift skipping 4500+ cards yesterday because
    its own marker was set, while other actors kept producing into its
    inbox — exactly the local-andon shape we don't allow.
    """
    from sweep.control_state import is_paused
    return is_paused()


def all_actor_status() -> list[dict]:
    """For diagnostics — return per-actor (actor, calls, share, used%)."""
    out = []
    for actor, share in SHARES.items():
        used = share_used(actor)
        out.append({
            "actor": actor,
            f"calls_{LOCAL_WINDOW_MINUTES}m": calls_last_window(actor),
            "share": share,
            "share_used_pct": round(100 * used, 1),
            "over_cap": used >= 1.0,
            "andon_pulled": is_blocked(actor),
        })
    # Untagged "unknown" bucket — calls that escaped attribution.
    unknown = calls_last_window("unknown")
    if unknown:
        out.append({
            "actor": "unknown",
            f"calls_{LOCAL_WINDOW_MINUTES}m": unknown,
            "share": None,
            "share_used_pct": None,
            "over_cap": False,
            "andon_pulled": False,
        })
    return out
