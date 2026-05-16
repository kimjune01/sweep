"""`sweep waste` — derived report on the seven wastes, rolled up from
events.jsonl + counters + gh_io cache stats.

Follows the lineage from raw signals (incr/event) to operator-readable
muda categories. Markdown output, glamour-rendered in the TUI's view
rotation, pipe-clean for grep/paste.
"""

from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict
from pathlib import Path

import typer

from sweep import gh_io, observe, outcomes as _outcomes


waste_app = typer.Typer(help="Lean waste report — defect/wait/inventory/over-processing",
                        no_args_is_help=False, invoke_without_command=True)


HOURS_LOOKBACK_DEFAULT = 24


def _events_in_window(hours: int) -> list[dict]:
    """Read events.jsonl, return entries newer than `hours` ago.
    Cheap one-pass parse; events.jsonl is append-only and usually small."""
    path = Path.home() / ".sweep" / "events.jsonl"
    if not path.exists():
        return []
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
    out: list[dict] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = e.get("ts", "")
        try:
            t = dt.datetime.fromisoformat(ts)
        except ValueError:
            continue
        if t >= cutoff:
            out.append(e)
    return out


def _pct(num: int, denom: int) -> str:
    if denom <= 0:
        return "—"
    return f"{100 * num / denom:.0f}%"


@waste_app.callback(invoke_without_command=True)
def waste(
    hours: int = typer.Option(HOURS_LOOKBACK_DEFAULT, "--hours",
                              help="Lookback window in hours"),
) -> None:
    """Markdown waste report. Defaults to the last 24 hours."""
    events = _events_in_window(hours)

    # ---------- Defects (andon halts, qa failures, skips) ----------
    qa_passed = sum(1 for e in events if e.get("kind") == "qa_converged"
                    and e.get("verdict") == "pass")
    qa_failed = sum(1 for e in events if e.get("kind") == "qa_converged"
                    and e.get("verdict") != "pass")
    halts = sum(1 for e in events if e.get("kind") == "pipeline_halted")
    qa_total = qa_passed + qa_failed
    defect_rate = _pct(qa_failed, qa_total)

    # ---------- Overproduction (prospect output that died in triage) ----------
    classified = [e for e in events if e.get("kind") == "pr_state_classified"]
    waited = sum(1 for e in classified if e.get("bucket") == "wait")
    over_pct = _pct(waited, len(classified))

    # ---------- Inventory (current inbox depth — point-in-time snapshot) ----------
    from sweep.inbox_state import inbox_states as _is
    depths = {a: len(_is(a)["queued"]) + len(_is(a)["in_flight"])
              for a in ("triaged", "investigate", "qa", "drip", "respondable", "retro")}

    # ---------- Over-processing (cache hit rate — proxy for redundant calls) ----------
    try:
        stats = gh_io.cache_stats()
        cache_total = sum(s["total"] for s in stats.values())
        cache_live = sum(s["live"] for s in stats.values())
    except Exception:
        cache_total = cache_live = 0
    cache_pct = _pct(cache_live, cache_total)

    # ---------- Mura (arrival variance per station) ----------
    arrivals_per_station: dict[str, list[str]] = defaultdict(list)
    for e in events:
        if e.get("kind") == "pr_state_classified":
            arrivals_per_station[e.get("bucket", "unknown")].append(e.get("ts", ""))

    # ---------- Skip / muri counters ----------
    skipped = observe.counters_with_prefix("halted_skip:") or {}
    paused_skipped = observe.counters_with_prefix("paused_skip:") or {}

    # ---------- Headliner: acceptance rate (external defect) ----------
    # The most expensive defect in this pipeline isn't a failed qa run —
    # it's a closed-unmerged PR. That spent maintainer attention, which
    # is the scarcest resource in the system, and decayed our standing
    # in their org for the next attempt. Hoist it to the top.
    days = max(1, hours // 24) or 1
    try:
        oc = _outcomes.outcomes(days=days)
        merged = oc.get("merged", 0)
        closed = oc.get("closed", 0)
        denom = merged + closed
        acceptance = _pct(merged, denom)
    except Exception:
        merged = closed = denom = 0
        acceptance = "—"

    print(f"# waste report — last {hours}h")
    print()
    print("## Headliner: maintainer attention spent")
    print()
    print(f"**Acceptance rate: {acceptance}** ({merged} merged / {denom} closed total)")
    print()
    print("_Closed-unmerged PRs are the ultimate waste — they consumed maintainer attention (non-renewable) and decayed standing in the org. Every other metric in this report is downstream of this number._")
    print()
    print("## Internal pipeline waste")
    print()
    print("| Waste | Signal | Value |")
    print("|---|---|---|")
    print(f"| Defects (internal) | qa_failed / total | {defect_rate} ({qa_failed}/{qa_total}) |")
    print(f"| Defects (internal) | andon halts (pipeline_halted) | {halts} |")
    print(f"| Overproduction | pr_state_classified → wait bucket | {over_pct} ({waited}/{len(classified)}) |")
    print(f"| Inventory | total in-flight + queued across stations | {sum(depths.values())} |")
    print(f"| Over-processing | gh_io cache live / total rows | {cache_pct} ({cache_live}/{cache_total}) |")
    print(f"| Muri | retro-halt-skipped counters | {sum(skipped.values())} |")
    print(f"| Muri | paused-skipped counters | {sum(paused_skipped.values())} |")
    print(f"| Mura | arrivals per station | "
          f"{', '.join(f'{k}={len(v)}' for k, v in sorted(arrivals_per_station.items())) or '—'} |")
    print()
    print("## Inventory by station")
    print()
    print("| Station | Depth |")
    print("|---|---:|")
    for station, depth in depths.items():
        print(f"| {station} | {depth} |")
    print()
    print("## Top counters")
    print()
    counters = observe.counters_all()
    top = sorted(counters.items(), key=lambda kv: -kv[1])[:10]
    if not top:
        print("_no counters yet_")
    else:
        print("| Counter | Value |")
        print("|---|---:|")
        for k, v in top:
            print(f"| {k} | {v} |")


def register(app: typer.Typer) -> None:
    app.add_typer(waste_app, name="waste")
