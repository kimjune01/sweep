"""`sweep punch` — coding factory cockpit. Single-line status + kanban table."""

from __future__ import annotations

import time

import typer

from sweep import glyphs
from sweep.inbox_state import inbox_states
from sweep.system import system_status


# Two caps per station — queue (backpressure) vs in-flight (concurrency).
# Humans have deeper queues; LLM actors stay shallow.
CAPS: dict[str, dict[str, int | None]] = {
    "triaged":     {"queued": 10, "in_flight": 3},  # LLM, fan-out friendly
    "investigate": {"queued": 5, "in_flight": 3},   # LLM, root-causing
    "qa":          {"queued": 3, "in_flight": 2},   # LLM, gates
    "drip":        {"queued": 5, "in_flight": 1},   # LLM, one push at a time
    "respondable": {"queued": 8, "in_flight": 2},   # you — real backlog signal
    "retro":       {"queued": None, "in_flight": None},  # in-review — geometry, not backlog
}

# Display names for the compressed flow line above the table. Differs from
# the table's actor-key column to read closer to the natural pipeline names.
FLOW_NAMES: dict[str, str] = {
    "triaged":     "Triage",
    "investigate": "Investigate",
    "qa":          "QA",
    "drip":        "Drip",
    "retro":       "In Review",
    "respondable": "Respondable",
}
FLOW_ORDER = ("triaged", "investigate", "qa", "drip", "retro", "respondable")


def register(app: typer.Typer) -> None:
    """Attach the punch command to a top-level Typer app."""
    app.command("punch")(punch)


def punch(
    include_wait: bool = typer.Option(False, "--include-wait", help="Also show retro/wait stations"),
    spark_minutes: int = typer.Option(10, help="Sparkline bucket size in minutes"),
    spark_buckets: int = typer.Option(12, help="Number of sparkline buckets (default 12 × 10min = 2h)"),
    rich_mode: bool = typer.Option(False, "--rich", help="Render Rich panels instead of markdown"),
    watch: bool = typer.Option(False, "--watch", "-w", help="Refresh continuously as a live dashboard"),
    interval: int = typer.Option(5, "--interval", "-i", help="Refresh interval (seconds) when --watch"),
) -> None:
    """Coding-factory cockpit — single status line + per-station kanban table.

    Default output is GitHub-flavored markdown — renders in Claude Code, looks
    fine in a plain terminal, and pipes cleanly to files / clipboard. Use
    --rich for Rich panels in a live terminal. --watch refreshes in place
    every --interval seconds.
    """
    if watch:
        try:
            while True:
                print("\x1b[2J\x1b[H", end="")
                _once(include_wait, spark_minutes, spark_buckets, rich_mode)
                print()
                print(f"_refreshes every {interval}s — Ctrl-C to exit_")
                time.sleep(interval)
        except KeyboardInterrupt:
            return
        return
    _once(include_wait, spark_minutes, spark_buckets, rich_mode)


# ---------------------------------------------------------- one tick


def _once(include_wait, spark_minutes, spark_buckets, rich_mode) -> None:
    actionable = ["triaged", "investigate", "qa", "drip", "respondable"]
    if include_wait:
        actionable = actionable + ["retro"]

    # Flow line always reads every station regardless of --include-wait —
    # geometry is the pipeline shape, not the action filter.
    flow_states: dict[str, dict[str, list[dict]]] = {
        actor: inbox_states(actor) for actor in FLOW_ORDER
    }
    states = {actor: flow_states[actor] for actor in actionable}

    rows = _build_rows(states, actionable, spark_minutes, spark_buckets)

    if rich_mode:
        _render_rich(rows)
        return

    _render_markdown(rows, flow_states, spark_minutes, spark_buckets)


def _build_rows(states, actionable, spark_minutes, spark_buckets):
    rows = []
    for actor in actionable:
        s = states[actor]
        queued = len(s["queued"])
        in_flight = len(s["in_flight"])
        q_cap = CAPS.get(actor, {}).get("queued")
        f_cap = CAPS.get(actor, {}).get("in_flight")
        all_msgs = s["queued"] + s["in_flight"] + s["done"]
        sparks = glyphs.bucketize(
            [m.get("ts", "") for m in all_msgs],
            spark_minutes, spark_buckets,
        )
        spark = glyphs.sparkline_pct(sparks, q_cap) or "·" * spark_buckets
        rate_str = f"{glyphs.rate_per_hour(sparks, spark_minutes):.1f}/h"
        var_glyph = glyphs.variance_glyph(sparks)
        rows.append((
            actor,
            queued,
            in_flight,
            rate_str,
            var_glyph,
            spark,
            glyphs.oldest_age_str(s["queued"] + s["in_flight"]),
            _status_for(actor, queued, in_flight, q_cap, f_cap),
        ))
    return rows


def _status_for(actor, queued, in_flight, q_cap, f_cap) -> str:
    if queued + in_flight == 0:
        return "idle"
    flags = []
    if q_cap is not None and queued >= q_cap:
        flags.append(f"**queue capped** ({queued}/{q_cap})")
    if f_cap is not None and in_flight >= f_cap:
        flags.append(f"**in-flight capped** ({in_flight}/{f_cap})")
    if flags:
        return ", ".join(flags)
    if actor == "retro":
        return "history"
    if in_flight > 0:
        return "working"
    return "queued"


# ---------------------------------------------------------- markdown render


def _render_flow(flow_states: dict[str, dict[str, list[dict]]]) -> str:
    """Compressed pipeline view: `[queued] Name(in_flight)` per station,
    `~` separated. Counts are elided when zero so the line stays scannable
    — only present pressure draws the eye."""
    parts: list[str] = []
    for actor in FLOW_ORDER:
        s = flow_states.get(actor) or {}
        queued = len(s.get("queued", []))
        in_flight = len(s.get("in_flight", []))
        name = FLOW_NAMES[actor]
        # ⌊ ⌋ are lower-corner brackets — only the bottom corners are
        # drawn, so a queued count reads as sitting in an open bucket.
        # Differentiates inboxes (containers caught from above) from WIP
        # (parens, sideways-opening, things in motion through hands).
        prefix = f"⌊{queued}⌋ " if queued > 0 else ""
        suffix = f"({in_flight})" if in_flight > 0 else ""
        parts.append(f"{prefix}{name}{suffix}")
    return " ~ ".join(parts)


def _render_markdown(rows, flow_states, spark_minutes, spark_buckets) -> None:
    sys = system_status()
    cpu = sys.get("cpu", 0.0)
    mem = sys.get("mem", 0.0)
    running = sys.get("running", [])

    print("# coding factory — kanban")
    print()

    runline = f"{len(running)} agents" if running else "0 agents"
    print(f"`cpu {cpu:.0f}% · mem {mem:.0f}% · {runline}`")
    print()

    print(f"`{_render_flow(flow_states)}`")
    print()

    print(f"| station | queued | in-flight | rate | var | trend ({spark_minutes}m × {spark_buckets}, % of cap) | oldest | status |")
    print( "|---|---:|---:|---:|:-:|---|---|---|")
    for actor, queued, in_flight, rate_str, var_glyph, spark, oldest, status in rows:
        print(
            f"| → {actor} | {queued} | {in_flight} | {rate_str} | `{var_glyph}` "
            f"| `{spark}` | {oldest} | {status} |"
        )


# ---------------------------------------------------------- rich render


def _render_rich(rows) -> None:
    from rich.columns import Columns
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text

    console = Console()

    source = Panel(
        Text("pr-state\n(dispatcher)\n\nreads GitHub\nroutes by bucket", justify="center"),
        title="intake",
        border_style="dim",
        width=18,
        padding=(0, 1),
    )
    panels = []
    for actor, queued, in_flight, rate_str, var_glyph, spark, oldest, status in rows:
        plain_status = status.replace("**", "")
        if "capped" in status:
            border, color = "red", "red bold"
        elif status == "idle":
            border, color = "green", "green"
        elif status == "history":
            border, color = "dim", "dim"
        elif status == "queued":
            border, color = "blue", "blue"
        else:
            border, color = "yellow", "yellow"
        body = Text()
        body.append("queued     ", style="dim"); body.append(f"{queued}\n", style="bold")
        body.append("in-flight  ", style="dim"); body.append(f"{in_flight}\n", style="bold")
        body.append("rate       ", style="dim"); body.append(f"{rate_str}\n", style="bold")
        body.append("var        ", style="dim"); body.append(f"{var_glyph}\n", style="bold")
        body.append(f"oldest     {oldest}\n", style="dim")
        body.append("trend      ", style="dim"); body.append(spark, style="cyan"); body.append("\n")
        body.append(plain_status, style=color)
        panels.append(Panel(body, title=f"[bold]{actor}[/]", border_style=border, width=22, padding=(0, 1)))

    console.print()
    console.print(Text("                       coding factory — kanban", style="bold dim"))
    console.print()
    console.print(Columns([source] + panels, equal=False, padding=(0, 1)))
    console.print()


