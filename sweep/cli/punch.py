"""`sweep punch` — coding factory cockpit. Cross-inbox kanban + outcomes."""

from __future__ import annotations

import datetime as dt
import time

import typer

from sweep import glyphs, org_state
from sweep.inbox_state import inbox_states
from sweep.outcomes import outcomes as fetch_outcomes
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
ACTION_HINT = {
    "triaged":     "issues scored, awaiting investigation (LLM)",
    "investigate": "root-cause new issues (LLM)",
    "qa":          "re-attest (CI failed / gates stale)",
    "drip":        "advance status (close / rebase / ship)",
    "respondable": "respond to reviewer",
    "retro":       "audit only (in-review bucket)",
}


def register(app: typer.Typer) -> None:
    """Attach the punch command to a top-level Typer app."""
    app.command("punch")(punch)


def punch(
    include_wait: bool = typer.Option(False, "--include-wait", help="Also show retro/wait audits"),
    spark_minutes: int = typer.Option(10, help="Sparkline bucket size in minutes"),
    spark_buckets: int = typer.Option(12, help="Number of sparkline buckets (default 12 × 10min = 2h)"),
    outcome_days: int = typer.Option(7, help="Outcomes window in days"),
    rich_mode: bool = typer.Option(False, "--rich", help="Render Rich panels instead of markdown"),
    no_outcomes: bool = typer.Option(False, "--no-outcomes", help="Skip the gh-backed outcomes fetch"),
    watch: bool = typer.Option(False, "--watch", "-w", help="Refresh continuously as a live dashboard"),
    interval: int = typer.Option(5, "--interval", "-i", help="Refresh interval (seconds) when --watch"),
) -> None:
    """Factory-floor kanban view + per-station punch list.

    Default output is GitHub-flavored markdown — renders in Claude Code, looks
    fine in a plain terminal, and pipes cleanly to files / clipboard. Use
    --rich for Rich panels in a live terminal. --watch refreshes in place
    every --interval seconds.
    """
    if watch:
        try:
            while True:
                print("\x1b[2J\x1b[H", end="")
                _once(include_wait, spark_minutes, spark_buckets, outcome_days, rich_mode, no_outcomes)
                print()
                print(f"_refreshes every {interval}s — Ctrl-C to exit_")
                time.sleep(interval)
        except KeyboardInterrupt:
            return
        return
    _once(include_wait, spark_minutes, spark_buckets, outcome_days, rich_mode, no_outcomes)


# ---------------------------------------------------------- one tick


def _once(include_wait, spark_minutes, spark_buckets, outcome_days, rich_mode, no_outcomes) -> None:
    actionable = ["triaged", "investigate", "qa", "drip", "respondable"]
    if include_wait:
        actionable = actionable + ["retro"]

    states: dict[str, dict[str, list[dict]]] = {}
    sections: dict[str, list[dict]] = {}
    in_flight_ids: dict[str, set[str]] = {}
    for actor in actionable:
        s = inbox_states(actor)
        states[actor] = s
        sections[actor] = sorted(s["queued"] + s["in_flight"], key=lambda x: x.get("ts", ""))
        in_flight_ids[actor] = {m.get("msg_id") for m in s["in_flight"]}

    rows = _build_rows(states, actionable, spark_minutes, spark_buckets)

    if rich_mode:
        _render_rich(rows, sections, actionable, include_wait)
        return

    _render_markdown(rows, sections, in_flight_ids, actionable, include_wait,
                     spark_minutes, spark_buckets, outcome_days, no_outcomes)


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


def _render_markdown(rows, sections, in_flight_ids, actionable, include_wait,
                     spark_minutes, spark_buckets, outcome_days, no_outcomes) -> None:
    sys = system_status()
    cpu = sys.get("cpu", 0.0)
    mem = sys.get("mem", 0.0)
    running = sys.get("running", [])

    print("# coding factory — kanban")
    print()
    runline = f"**{len(running)} agents running**" if running else "_no agents running_"
    print(f"`system`  cpu {cpu:.0f}%  ·  mem {mem:.0f}%  ·  {runline}")
    if running:
        for wf in running[:5]:
            age = _age(wf.get("started"))
            print(f"- `{wf.get('type', '?')}` `{wf.get('id', '?')}` _running {age}_")
    print()
    blocked = org_state.blocked_orgs()
    if blocked:
        # Show the heaviest 5 (most open PRs) + total count. JIT principle:
        # if many orgs are blocked, prospect has correctly stopped surfacing
        # work — the constraint is review throughput, not upstream supply.
        heavy = sorted(blocked.items(), key=lambda kv: -len(kv[1]))[:5]
        total_prs = sum(len(prs) for prs in blocked.values())
        head = ", ".join(f"{o}({len(prs)})" for o, prs in heavy)
        print(f"`org gate`  {len(blocked)} orgs blocked ({total_prs} PRs in review)  ·  heaviest: {head}")
        print()
    print("`intake: pr-state` (reads GitHub, classifies, routes by bucket) →")
    print()
    print(f"| station | queued | in-flight | rate | var | trend ({spark_minutes}m × {spark_buckets}, % of cap) | oldest | status |")
    print( "|---|---:|---:|---:|:-:|---|---|---|")
    for actor, queued, in_flight, rate_str, var_glyph, spark, oldest, status in rows:
        print(
            f"| → {actor} | {queued} | {in_flight} | {rate_str} | `{var_glyph}` "
            f"| `{spark}` | {oldest} | {status} |"
        )
    print()

    total = sum(len(sections[a]) for a in actionable if a != "retro")
    if total == 0 and not include_wait:
        print("_nothing actionable — pipeline idle_")
    else:
        for actor in actionable:
            msgs = sections[actor]
            if not msgs:
                continue
            if actor == "retro" and not include_wait:
                continue
            print(f"## {actor} ({len(msgs)}) — {ACTION_HINT[actor]}")
            print()
            for m in msgs:
                repo = m.get("repo", "?")
                pr = m.get("pr") or "-"
                payload = m.get("payload") or {}
                reason = payload.get("reason", "")
                ts = m.get("ts", "")[:19]
                url = f"https://github.com/{repo}/pull/{pr}"
                prefix = "✈️ " if m.get("msg_id") in in_flight_ids.get(actor, set()) else ""
                print(f"- {prefix}**[{repo}#{pr}]({url})** — {reason}  _({ts})_")
            print()

    if no_outcomes:
        return
    _render_outcomes(outcome_days)


def _render_outcomes(days: int) -> None:
    o = fetch_outcomes(days)
    merged = o["merged"]
    closed = o["closed"]
    total = merged + closed
    ratio = (merged / total * 100) if total else None
    days = o["days"]
    merge_dither = glyphs.dither(o["merged_per_day"])
    close_dither = glyphs.dither(o["closed_per_day"])
    end_date = dt.date.fromisoformat(o["end"])
    day_labels = "".join(
        (end_date - dt.timedelta(days=days - 1 - i)).strftime("%a")[0]
        for i in range(days)
    )

    print(f"## outcomes (last {days}d — what actually merged)")
    print()
    print("| metric | value |")
    print("|---|---:|")
    print(f"| merged | {merged} |")
    print(f"| closed (not merged) | {closed} |")
    if ratio is not None:
        print(f"| merge ratio | {ratio:.0f}% |")
    else:
        print("| merge ratio | — _(no outcomes)_ |")
    print(f"| daily merge rate | {merged / days:.1f} |")
    print()
    print("```")
    print(f"day   {day_labels}    ← oldest → today")
    print(f"merge {merge_dither}    {merged} total")
    print(f"close {close_dither}    {closed} total")
    print("```")
    print()


# ---------------------------------------------------------- rich render


def _render_rich(rows, sections, actionable, include_wait) -> None:
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

    for actor in actionable:
        msgs = sections[actor]
        if not msgs:
            continue
        if actor == "retro" and not include_wait:
            continue
        console.print(f"[bold]{actor}[/] ({len(msgs)}) — [dim]{ACTION_HINT[actor]}[/]")
        for m in msgs:
            intent = m.get("intent", "?")
            repo = m.get("repo", "?")
            pr = m.get("pr") or "-"
            payload = m.get("payload") or {}
            reason = payload.get("reason", "")
            console.print(f"  [bold cyan]{repo}#{pr}[/]  [{intent}]  {reason}")
        console.print()


def _age(started: str | None) -> str:
    if not started:
        return ""
    try:
        t = dt.datetime.fromisoformat(started.replace("Z", "+00:00"))
        secs = int((dt.datetime.now(dt.timezone.utc) - t).total_seconds())
        return f"{secs}s" if secs < 60 else f"{secs//60}m"
    except (ValueError, AttributeError):
        return ""
