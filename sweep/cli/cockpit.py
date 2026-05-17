"""`sweep cockpit` — factory floor cockpit. Single status line + compressed
flow + per-station table. Pairs with `sweep lanes` (swim-lane detail)."""

from __future__ import annotations

import contextlib
import io
import shutil
import subprocess
import sys
import time

import typer

from sweep import control_state, glyphs, retro_state
from sweep.inbox_state import inbox_states
from sweep.system import system_status


# Two caps per station — queue (backpressure) vs in-flight (concurrency).
# Humans have deeper queues; LLM actors stay shallow.
CAPS: dict[str, dict[str, int | None]] = {
    "scout":       {"queued": 3, "in_flight": 1},   # search cards from triage/heartbeat
    "sift":        {"queued": 100, "in_flight": 1}, # issue cards from scout (fan-out of one search)
    "triaged":     {"queued": 10, "in_flight": 3},  # LLM, fan-out friendly
    "investigate": {"queued": 5, "in_flight": 5},   # LLM, root-causing
    "immunize":    {"queued": 10, "in_flight": 1},  # anti-AI routing to slop-offer
    "tissue":      {"queued": 5, "in_flight": 1},   # side-hatch comment drafts
    "bless":       {"queued": 5, "in_flight": 1},   # response classifier-router
    "wipe":        {"queued": 5, "in_flight": 1},   # operator-approved posts
    "qa":          {"queued": 5, "in_flight": 5},   # LLM, gates
    "respond":     {"queued": 5, "in_flight": 1},   # auto-responder (rebase/close/publish via /drip)
    "human": {"queued": 8, "in_flight": 2},   # you — real backlog signal
    "retro":       {"queued": None, "in_flight": None},  # in-review — geometry, not backlog
}

# Display names for the compressed flow line above the table. Differs from
# the table's actor-key column to read closer to the natural pipeline names.
FLOW_NAMES: dict[str, str] = {
    "scout":       "Scout",
    "sift":        "Sift",
    "triaged":     "Triage",
    "investigate": "Investigate",
    "immunize":    "Immunize",
    "tissue":      "Tissue",
    "bless":       "Bless",
    "wipe":        "Wipe",
    "qa":          "QA",
    "respond":     "Respond",
    "retro":       "In Review",
    "human":       "Human",
}
FLOW_ORDER = ("scout", "sift", "triaged", "immunize", "investigate", "tissue", "bless", "wipe", "qa", "respond", "retro", "human")

def register(app: typer.Typer) -> None:
    """Attach the cockpit command to a top-level Typer app."""
    app.command("cockpit")(cockpit)


def cockpit(
    include_wait: bool = typer.Option(False, "--include-wait", help="Also show retro/wait stations"),
    spark_minutes: int = typer.Option(20, help="Sparkline bucket size in minutes"),
    spark_buckets: int = typer.Option(12, help="Number of sparkline buckets (default 12 × 20min = 4h)"),
    rich_mode: bool = typer.Option(False, "--rich", help="Render Rich panels instead of markdown"),
    plain: bool = typer.Option(False, "--plain", help="Force plain markdown (default: styled via glow when stdout is a TTY)"),
    watch: bool = typer.Option(False, "--watch", "-w", help="Refresh continuously as a live dashboard"),
    interval: int = typer.Option(5, "--interval", help="Refresh interval (seconds) when --watch"),
) -> None:
    """Factory-floor cockpit — single status line, compressed pipeline flow,
    per-station table. The operator's "what's the line doing right now" view.

    Pairs with `sweep lanes` (per-station swim lanes with PR detail). Cockpit
    is the gemba view; lanes is the work-in-progress board.

    Defaults to styled output via glow when stdout is a TTY (you ran the
    command yourself). Pipes / redirects get raw markdown so scripts can
    parse it. Pass --plain to force raw even in a TTY.
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
    # Styled-by-default in a TTY when glow is available. Pipes / redirects /
    # --plain all fall through to raw markdown so scripts can parse the
    # output and so the command always produces something usable.
    if not plain and sys.stdout.isatty() and shutil.which("glow"):
        _render_through_glow(include_wait, spark_minutes, spark_buckets, rich_mode)
        return
    _once(include_wait, spark_minutes, spark_buckets, rich_mode)


def _render_through_glow(include_wait, spark_minutes, spark_buckets, rich_mode) -> None:
    """Capture the markdown output and pipe it through glow's pager so the
    operator gets styled rendering with q-to-quit. Falls back to plain
    print + an inline hint when glow isn't on PATH so the command always
    produces something usable."""
    if not shutil.which("glow"):
        _once(include_wait, spark_minutes, spark_buckets, rich_mode)
        print()
        print("_glow not installed — `brew install charmbracelet/tap/glow` for styled rendering_",
              file=sys.stderr)
        return
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        _once(include_wait, spark_minutes, spark_buckets, rich_mode)
    try:
        proc = subprocess.Popen(["glow", "-p", "-"], stdin=subprocess.PIPE)
        proc.communicate(input=buf.getvalue().encode())
    except KeyboardInterrupt:
        pass


# ---------------------------------------------------------- one tick


def _once(include_wait, spark_minutes, spark_buckets, rich_mode) -> None:
    actionable = ["scout", "sift", "triaged", "immunize", "investigate", "tissue", "bless", "wipe", "qa", "respond", "human"]
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


def _knob_line() -> str:
    """One-line summary of the knobs that actually change decisions.

    Only operator-tunable surfaces belong here. View-layer thresholds
    (CAPS in cockpit.py) are NOT knobs — they're display formatting
    rules. WIP isn't shown for the same reason: it's a code constant
    in qa_actor.py and SkillActor, not a runtime knob, so surfacing
    it as one misleads.
    """
    from sweep.activities.sift import (
        _min_complexity, _search_limit, _min_issue_age_minutes,
        _warm_org_fan_out_cap, _warm_org_issue_limit,
    )
    return (
        f"floor = {_min_complexity()}    ·    "
        f"search = {_search_limit()}    ·    "
        f"warm = {_warm_org_fan_out_cap()}×{_warm_org_issue_limit()}    ·    "
        f"age ≥ {_min_issue_age_minutes()}m"
    )


def _andon_banner() -> str | None:
    """Read ~/.sweep/control/andon/*.json — one file per halted actor —
    and return a loud red banner if any exist. None when the dir is empty
    or missing. The banner names each halted actor and the proximate
    reason so the operator knows what to clear (`sweep andon clear
    <actor>`) or fix.
    """
    import json as _json
    from pathlib import Path
    andon_dir = Path.home() / ".sweep" / "control" / "andon"
    if not andon_dir.exists():
        return None
    files = sorted(andon_dir.glob("*.json"))
    if not files:
        return None
    lines = ["🚨  **ANDON — LINE STOPPED**  🚨", ""]
    for f in files:
        try:
            d = _json.loads(f.read_text())
        except Exception:
            continue
        actor = d.get("actor", f.stem)
        reason = (d.get("reason") or "")[:200]
        ts = d.get("ts", "")
        lines.append(f"- 🔴 **{actor}** — {reason}  _( {ts} )_")
    lines.append("")
    lines.append("_Clear with_ `sweep andon clear <actor>` _once fixed._")
    return "\n".join(lines)


def _claude_sub_chip() -> str | None:
    """Read ~/.sweep/control/claude_usage.json (written by UsagePoller).
    Returns 'sub 67%/12%' (5h/weekly) or None when no data yet."""
    import json as _json
    from pathlib import Path
    path = Path.home() / ".sweep" / "control" / "claude_usage.json"
    if not path.exists():
        return None
    try:
        d = _json.loads(path.read_text())
    except Exception:
        return None
    parts = []
    if "five_hour_pct" in d:
        parts.append(f"{d['five_hour_pct']}%/5h")
    if "weekly_pct" in d:
        parts.append(f"{d['weekly_pct']}%/wk")
    if not parts:
        return None
    return "sub " + " ".join(parts)


def _sift_info() -> dict:
    """Cockpit chip for the sift actor. Returns {state, age}.
    `state`: 'empty ×N' streak label, or '' when streak is zero.
    `age`: human-compact time since the actor's most recent activity,
           sourced from the sift inbox file mtime.

    No temporal query: sift is now a SkillActor and its empty-streak
    counter lives in `~/.sweep/state/sift_actor.json` (file-backed
    across restarts). Andon/pause state already has its own banner, so
    the chip stops trying to duplicate it — bare 'ready' was noise."""
    import datetime as dt
    import json
    from pathlib import Path

    state_path = Path.home() / ".sweep" / "state" / "sift_actor.json"
    inbox_path = Path.home() / ".sweep" / "inbox" / "sift.jsonl"

    streak = 0
    if state_path.exists():
        try:
            streak = int(json.loads(state_path.read_text()).get("empty_streak", 0))
        except (json.JSONDecodeError, OSError, ValueError):
            streak = 0
    base = f"empty ×{streak}" if streak > 0 else ""

    age = ""
    if inbox_path.exists():
        try:
            secs = int(dt.datetime.now().timestamp() - inbox_path.stat().st_mtime)
            if secs < 60:
                age = f"{secs}s"
            elif secs < 3600:
                age = f"{secs // 60}m"
            else:
                age = f"{secs // 3600}h"
        except OSError:
            pass

    return {"state": base, "age": age}


def _window_label(spark_minutes: int, spark_buckets: int) -> str:
    """Compact window label: '4hrs' beats '20m × 12, % of cap'. Reader
    doesn't care about bucket arithmetic; they care about depth."""
    total_min = spark_minutes * spark_buckets
    if total_min % 60 == 0:
        hours = total_min // 60
        return f"{hours}hr" if hours == 1 else f"{hours}hrs"
    return f"{total_min}min"


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
        # Always shown (including ⌊0⌋) so columns read as a row of
        # consistent chips, not an irregular gap of names.
        suffix = f"({in_flight})" if in_flight > 0 else ""
        parts.append(f"⌊{queued}⌋ {name}{suffix}")
    return " ~ ".join(parts)


def _render_markdown(rows, flow_states, spark_minutes, spark_buckets) -> None:
    sys = system_status()
    cpu = sys.get("cpu", 0.0)
    mem = sys.get("mem", 0.0)

    print("# Sweep: Coding Factory")
    print()

    # Loud banners for line-stopped states. Both andon (involuntary —
    # something broke) and pause (voluntary — operator stopped the line)
    # share the same visual weight: the line is not running, regardless
    # of cause. Silent when neither applies.
    banner = _andon_banner()
    if banner:
        print(banner)
        print()
    if control_state.is_paused():
        print("🚦  **PAUSED — operator stopped the line**  🚦")
        print()
        print("_Resume with_ `sweep pause off`.")
        print()

    # Status line: only signals the operator can act on. Actor count is
    # implementation detail (it's always "the actors that should be
    # running"); cockpit isn't a process monitor. Use `sweep status` for
    # that.
    parts = [f"cpu {cpu:.0f}%", f"mem {mem:.0f}%"]
    sub_chip = _claude_sub_chip()
    if sub_chip:
        parts.append(sub_chip)
    # Operator flags render only when active — quiet state stays quiet.
    # Pause is hoisted into the top banner (it stops the line); only
    # DRY remains a chip here, since rehearsal doesn't stop the line.
    # 🌵 (cactus, "rehearsing in the desert").
    if control_state.is_dry():
        parts.append("🌵 DRY")
    # Retro state appended only when there's something to flag — halt is
    # the strongest signal, actionable is softer. Quiet retros (empty-P
    # accumulating chains) don't earn cockpit space.
    if retro_state.is_halted():
        # Uppercase RETRO mirrors the urgency: 🌱 retro is "at your pace,"
        # 📋 RETRO is "the line is stopped on this." Same noun, different
        # voice. The badge names the cause (retro) over the effect (halted).
        parts.append("📋 RETRO")
    else:
        retros = retro_state.list_retros()
        actionable = any(retro_state.has_prescription(r) for r in retros)
        if actionable:
            # Names the kind of thing waiting, not a count — the inbox below
            # carries the slug. Multiplicity is implicit; the operator's job
            # is "go look at retro," not "count retros."
            parts.append("🌱 retro")
    print(" · ".join(parts))
    print()

    # Knobs above the table — pipeline configuration, the state of
    # the world the operator can change. Reads as "here's how the line
    # is tuned" right under cpu/mem.
    pinfo = _sift_info()
    age = f" ({pinfo['age']})" if pinfo.get("age") else ""
    state_chip = f"    ·    {pinfo['state']}" if pinfo.get("state") else ""
    print(f"🎛   Sift Controls{age}:   {_knob_line()}{state_chip}")
    print()

    print(f"| Station | Queued | In-flight | Rate | Var | Trend ( {_window_label(spark_minutes, spark_buckets)} ) | Oldest | Status |")
    print( "|---|---:|---:|---:|:-:|---|---|---|")
    for actor, queued, in_flight, rate_str, var_glyph, spark, oldest, status in rows:
        print(
            f"| {FLOW_NAMES.get(actor, actor)} | {queued} | {in_flight} | {rate_str} | `{var_glyph}` "
            f"| `{spark}` | {oldest} | {status} |"
        )

    # Inbox + in-review below the table — "what's queued for human
    # attention" group. Both hidden when zero.
    from sweep.cli.inbox import operator_inbox_lines
    n = len(operator_inbox_lines())
    if n:
        print()
        print(f"📥   {n}  _| `sweep inbox`_")
    # Retro inbox is the wait-bucket audit trail; pr-state appends
    # a fresh entry every poll cycle for each open PR, so raw length
    # over-counts. Dedupe by (repo, pr) to get "PRs currently in
    # review," which is what the chip is trying to convey.
    retro_queued = (flow_states.get("retro") or {}).get("queued", [])
    retro_count = len({(m.get("repo"), m.get("pr")) for m in retro_queued})
    if retro_count:
        print()
        print(f"👀   {retro_count} in review")

    # Operator-toggled holds. Each flag file presence emits one line so
    # the cockpit reminds the operator that an actor is intentionally
    # held — easy to forget after the bounce. Add new flags here as
    # the pattern proliferates.
    from pathlib import Path as _Path
    _wipe_flag = _Path.home() / ".sweep" / "control" / "wipe_disabled"
    if _wipe_flag.exists():
        print()
        print("🚧   wipe disabled — `rm ~/.sweep/control/wipe_disabled` to enable")


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
    console.print(Text("                       coding factory — lanes", style="bold dim"))
    console.print()
    console.print(Columns([source] + panels, equal=False, padding=(0, 1)))
    console.print()


