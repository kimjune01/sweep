"""`sweep floor` — the factory floor view. One screen, four sections.

The factory metaphor at a glance:
  andon     — retro pager state + halt flag (is the line stopped?)
  conveyor  — inbox depths per actor (work moving through stations)
  tools     — token spend + gh cache pressure (what the line is consuming)
  output    — merged / closed counts (what the line is producing)

Subsumes the read sides of `punch`, `board`, `retro status`,
`observe counters`, `attest tokens`, and `attest gh-cache` into a single
operator view. Each section reuses the same helpers the dedicated commands
call, so the floor stays in sync with the per-subcommand renderings.

Read-only by design. The factory floor is for *seeing*; acting happens
through the actor-specific commands (`sweep retro discard`, `sweep qa
clear`, etc.) once you've decided what the floor is telling you.
"""

from __future__ import annotations

import typer

from sweep import attestations, gh_io, retro_state
from sweep.inbox_state import inbox_states
from sweep.outcomes import outcomes as fetch_outcomes


# Actor stations on the conveyor, in pipeline flow order.
STATIONS = ("triaged", "investigate", "qa", "drip", "respondable", "retro")


def register(app: typer.Typer) -> None:
    """Attach the floor command to a top-level Typer app."""
    app.command("floor")(floor)


def floor(
    outcome_days: int = typer.Option(7, help="Outcomes window in days"),
    no_outcomes: bool = typer.Option(False, "--no-outcomes",
                                      help="Skip the gh-backed outcomes fetch"),
) -> None:
    """One-screen factory floor view."""
    _render_andon()
    print()
    _render_conveyor()
    print()
    _render_tools()
    if not no_outcomes:
        print()
        _render_output(outcome_days)


# ---------------------------------------------------------------- andon


def _render_andon() -> None:
    print("## andon")
    retros = retro_state.list_retros()
    halted = retro_state.is_halted()
    state = "HALTED" if halted else "running"
    # 📋 in the summary line is the glance-able "you owe an Attend" signal —
    # at least one pending retro has a non-empty P. Per-retro lines below
    # carry the same emoji so the operator can see which one to read.
    actionable = [r for r in retros if retro_state.has_prescription(r)]
    # Emoji only when something demands action. Two attention states:
    #   📋  halted — line is stopped, attend now (strongest signal)
    #   🌱  actionable — fold a prescription back at your pace
    # Otherwise quiet — operator can walk past.
    if halted:
        badge = " 📋"
    elif actionable:
        badge = " 🌱"
    else:
        badge = ""
    print(f"retros: {len(retros)}/{retro_state.RETRO_CAP}{badge}  "
          f"pipeline: {state}")
    if not retros:
        print("  (no pending retros)")
        return
    for r in retros:
        has_p = retro_state.has_prescription(r)
        flag = "🌱 actionable" if has_p else "accumulating"
        print(f"  {r.written_at.isoformat(timespec='minutes')}  "
              f"{r.name}  {flag}")


# ---------------------------------------------------------------- conveyor


def _render_conveyor() -> None:
    print("## conveyor")
    width = max(len(s) for s in STATIONS)
    for actor in STATIONS:
        states = inbox_states(actor)
        q = len(states.get("queued", []))
        f = len(states.get("in_flight", []))
        d = len(states.get("done", []))
        # While the started/acks writer side isn't wired (q7 backlog),
        # in_flight / done are always 0 — show queued first so the
        # operator sees the load even with the writer gap.
        print(f"  {actor:<{width}}  queued {q:>3}   "
              f"in_flight {f:>2}   done {d:>3}")


# ---------------------------------------------------------------- tools


def _render_tools() -> None:
    print("## tools")
    tokens = attestations.token_summary()
    if tokens:
        for nick, t in sorted(tokens.items()):
            print(f"  {nick:<8}  in {t.get('input_tokens', 0):>6}   "
                  f"out {t.get('output_tokens', 0):>6}   "
                  f"calls {t.get('calls', 0):>3}")
    else:
        print("  (no LLM calls recorded)")
    print()
    cache = gh_io.cache_stats()
    if cache:
        width = max(len(e) for e in cache)
        for endpoint, s in sorted(cache.items()):
            print(f"  gh {endpoint:<{width}}  live {s['live']:>3}   "
                  f"total {s['total']:>3}")
    else:
        print("  (gh cache empty)")


# ---------------------------------------------------------------- output


def _render_output(days: int) -> None:
    print(f"## output  (last {days}d)")
    try:
        o = fetch_outcomes(days)
    except Exception as e:
        print(f"  (outcomes unavailable: {e})")
        return
    merged = o.get("merged", 0)
    closed = o.get("closed", 0)
    total = merged + closed
    if total > 0:
        ratio = int(round(100 * merged / total))
        ratio_s = f"{ratio}%"
    else:
        ratio_s = "—"
    rate_s = f"{merged / days:.1f}" if days > 0 else "—"
    print(f"  merged {merged}   closed (not merged) {closed}   "
          f"merge ratio {ratio_s}   daily rate {rate_s}")
