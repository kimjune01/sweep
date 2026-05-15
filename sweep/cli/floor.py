"""`sweep floor` — the factory floor view, rendered with ascii indicators.

Four sections in pipeline-flow order:

  andon     retro pager state + halt flag — is the line stopped?
  conveyor  queue-depth bars per station, with cap comparison
  tools     token usage + gh cache hit rate as horizontal bars
  output    merge ratio + daily rate as horizontal bars

Bars use sweep.glyphs block characters. Each section reuses the same
helpers the dedicated commands (punch, board, attest, retro) consume,
so the floor stays in sync without duplicating state. Read-only —
actions still go through the actor-specific commands.

The factory metaphor: the operator sees the line at a glance. Bars
filling = stations loading; bars overflowing = stations over cap;
🌱 = a fold-back is waiting; 📋 = the line is stopped.
"""

from __future__ import annotations

import datetime as dt

import typer

from sweep import attestations, gh_io, retro_state
from sweep.cli.punch import CAPS
from sweep.inbox_state import inbox_states
from sweep.outcomes import outcomes as fetch_outcomes


# Actor stations on the conveyor, in pipeline flow order.
STATIONS = ("triaged", "investigate", "qa", "drip", "respondable", "retro")

BAR_WIDTH = 14
BAR_FULL = "█"
BAR_EMPTY = "░"


def register(app: typer.Typer) -> None:
    """Attach the floor command to a top-level Typer app."""
    app.command("floor")(floor)


def floor(
    outcome_days: int = typer.Option(7, help="Outcomes window in days"),
    no_outcomes: bool = typer.Option(False, "--no-outcomes",
                                      help="Skip the gh-backed outcomes fetch"),
) -> None:
    """One-screen factory floor with ascii indicators."""
    _render_header()
    print()
    _render_conveyor()
    print()
    _render_tools()
    if not no_outcomes:
        print()
        _render_output(outcome_days)


# ---------------------------------------------------------------- bars


def _bar(value: float, cap: float, width: int = BAR_WIDTH) -> str:
    """Horizontal bar of fixed total width (BAR_WIDTH + 1 overflow slot).
    Over-cap fills the bar and lights the trailing ▶; under-cap leaves
    the trailing slot blank so columns align across rows."""
    overflow_slot = " "
    if cap <= 0:
        return BAR_EMPTY * width + overflow_slot
    fill = value / cap
    n = min(int(round(fill * width)), width)
    bar = BAR_FULL * n + BAR_EMPTY * (width - n)
    if fill > 1.0:
        overflow_slot = "▶"
    return bar + overflow_slot


def _pct_bar(pct: float, width: int = BAR_WIDTH) -> str:
    """Percent (0.0-100.0) as a fixed-width bar."""
    return _bar(pct, 100.0, width)


# ---------------------------------------------------------------- header


def _render_header() -> None:
    now = dt.datetime.now(dt.timezone.utc).strftime("%H:%MZ")
    retros = retro_state.list_retros()
    halted = retro_state.is_halted()
    actionable = any(retro_state.has_prescription(r) for r in retros)

    if halted:
        badge = "📋"
        pipeline = "HALTED"
    elif actionable:
        badge = "🌱"
        pipeline = "running"
    else:
        badge = " "  # keep column width stable
        pipeline = "running"

    line = f"sweep floor {'─' * 12} {now} {badge}  pipeline {pipeline}  retros {len(retros)}/{retro_state.RETRO_CAP}"
    print(line)
    if retros:
        for r in retros:
            mark = "🌱" if retro_state.has_prescription(r) else "·"
            print(f"           {mark} {r.name}  ({r.written_at.isoformat(timespec='minutes')})")


# ---------------------------------------------------------------- conveyor


def _render_conveyor() -> None:
    print("conveyor")
    name_w = max(len(s) for s in STATIONS)
    for actor in STATIONS:
        states = inbox_states(actor)
        q = len(states.get("queued", []))
        f = len(states.get("in_flight", []))
        d = len(states.get("done", []))
        caps = CAPS.get(actor, {})
        q_cap = caps.get("queued")
        f_cap = caps.get("in_flight")

        if q_cap:
            q_str = f"{q:>2}/{q_cap}"
            q_bar = _bar(q, q_cap)
        else:
            # No cap (retro is geometry, not backlog). Peak-relative against 20.
            q_str = f"{q:>2}"
            q_bar = _bar(q, max(q, 20))

        f_mark = ("●" * f) if f else "·"
        d_mark = f"{d}" if d else "·"

        print(f"  {actor:<{name_w}}  {q_bar}  q {q_str:<5}  "
              f"f {f_mark:<3}  d {d_mark}")


# ---------------------------------------------------------------- tools


def _render_tools() -> None:
    print("tools")
    tokens = attestations.token_summary()
    if tokens:
        # Peak across all models so bars are comparable.
        peak_in = max((t.get("input_tokens", 0) for t in tokens.values()), default=1) or 1
        peak_out = max((t.get("output_tokens", 0) for t in tokens.values()), default=1) or 1
        for nick, t in sorted(tokens.items()):
            tin = t.get("input_tokens", 0)
            tout = t.get("output_tokens", 0)
            calls = t.get("calls", 0)
            print(f"  {nick:<8}  in  {_bar(tin, peak_in)} {tin:>6}    "
                  f"out {_bar(tout, peak_out)} {tout:>5}    "
                  f"calls {calls}")
    else:
        print("  (no LLM calls recorded)")
    cache = gh_io.cache_stats()
    if cache:
        total_live = sum(s["live"] for s in cache.values())
        total_all = sum(s["total"] for s in cache.values())
        pct = (100.0 * total_live / total_all) if total_all else 0.0
        print(f"  gh cache  {_pct_bar(pct)} "
              f"{pct:>4.0f}% live   ({total_live}/{total_all} across "
              f"{len(cache)} endpoints)")


# ---------------------------------------------------------------- output


def _render_output(days: int) -> None:
    print(f"output  (last {days}d)")
    try:
        o = fetch_outcomes(days)
    except Exception as e:
        print(f"  (outcomes unavailable: {e})")
        return
    merged = o.get("merged", 0)
    closed = o.get("closed", 0)
    total = merged + closed
    ratio = (100.0 * merged / total) if total else 0.0
    rate = (merged / days) if days > 0 else 0.0
    # Rate bar caps at a 10/day default — past that, bar overflows.
    print(f"  merge ratio  {_pct_bar(ratio)} {ratio:>4.0f}%   "
          f"({merged} merged / {closed} closed)")
    print(f"  daily rate   {_bar(rate, 10.0)} {rate:>4.1f}/day")
