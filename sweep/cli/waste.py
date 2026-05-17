"""`sweep waste` — what's wasting our finite resources in the JIT shop.

Three actual waste signals in this factory:
  1. Dead slots — filled org kanban slot whose PR has stalled. The slot
     is consumed forever; we can't open another PR to that org.
  2. Bad org picks — orgs whose historical acceptance is 0/many. Future
     slot fills there are reliably wasted.
  3. Stuck internal WIP — items pulled into our funnel that never reached
     "PR opened." Dead inventory we created and never shipped.

Plus operational hygiene: GitHub cache hit rate.

Everything else (cycle time, internal throughput, arrival sparklines)
is either rhythm or out of our control — not waste.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from collections import defaultdict
from pathlib import Path

import typer

from sweep import gh_io, glyphs, observe, org_state, outcomes as _outcomes, retro_state
from sweep.inbox_state import inbox_states


waste_app = typer.Typer(help="Real waste in the JIT pipeline — dead slots, bad picks, stuck WIP",
                        no_args_is_help=False, invoke_without_command=True)


STATIONS = ("triaged", "investigate", "qa", "respond", "human", "retro")

# Pipeline epoch — the tinygrad ban (geohot closed PR #16113), which
# triggered the rebuild of the system into its current form. Pre-epoch
# contributions are forgotten old manual work, not "picks" the current
# pipeline made.
PIPELINE_EPOCH = dt.datetime(2026, 5, 9, 0, 11, 43, tzinfo=dt.timezone.utc)


def _fmt_age(seconds: float) -> str:
    if seconds < 60: return f"{int(seconds)}s"
    if seconds < 3600: return f"{int(seconds // 60)}m"
    if seconds < 86400: return f"{seconds / 3600:.1f}h"
    return f"{seconds / 86400:.1f}d"


def _parse_ts(s: str) -> dt.datetime | None:
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _age_histogram_30d(timestamps: list[dt.datetime],
                       now: dt.datetime) -> list[int]:
    """Bucket each timestamp by age-in-days. 30 buckets: [0d, 1d, …, 29d+]."""
    buckets = [0] * 30
    for t in timestamps:
        d = (now - t).days
        if d < 0: d = 0
        if d > 29: d = 29
        buckets[d] += 1
    return buckets


_SPARK = " ▁▂▃▄▅▆▇█"


def _spark_floored(counts: list[int]) -> str:
    """Sparkline that never hides nonzero counts and shows zeros as '·'."""
    peak = max(counts) or 1
    out = []
    for c in counts:
        if c == 0:
            out.append("·")
        else:
            level = max(1, min(8, int(round(c * 8 / peak))))
            out.append(_SPARK[level])
    return "".join(out)


def _render_age_spark(label: str, buckets: list[int]) -> list[str]:
    """30-char sparkline with axis hints. Empty if no data."""
    if not buckets or sum(buckets) == 0:
        return []
    buckets = list(reversed(buckets))  # past on the left, present on the right
    spark = _spark_floored(buckets)
    axis = "29d+" + " " * (30 - 6) + "0d"
    return ["```", spark, axis, "```", ""]


def _render_table(headers: list[str], rows: list[list[str]],
                  aligns: list[str] | None = None) -> list[str]:
    """Render a code-fenced aligned table. aligns is 'l' or 'r' per col."""
    aligns = aligns or (["l"] * len(headers))
    cols = list(zip(headers, *rows)) if rows else [(h,) for h in headers]
    widths = [max(len(str(c)) for c in col) for col in cols]
    def fmt(cells: list[str]) -> str:
        return "   ".join(
            (str(c).rjust(w) if aligns[i] == "r" else str(c).ljust(w))
            for i, (c, w) in enumerate(zip(cells, widths))
        ).rstrip()
    out = ["```", fmt(headers)]
    for r in rows:
        out.append(fmt(r))
    out += ["```", ""]
    return out


@waste_app.callback(invoke_without_command=True)
def waste(
    pick_window_days: int = typer.Option(0, "--pick-window",
        help="Lookback for per-org acceptance (default: since pipeline epoch)"),
    score_window_days: int = typer.Option(7, "--score-window",
        help="Sliding window for the scoreboard headline numbers"),
    wip_stuck_days: int = typer.Option(3, "--wip-stuck",
        help="An internal inbox item is stuck if older than this"),
) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    if pick_window_days <= 0:
        pick_window_days = max(1, (now - PIPELINE_EPOCH).days + 1)
    lines: list[str] = []

    # ====================================================================
    # SCOREBOARD — the numbers the README broadcasts (hoisted to the top)
    # ====================================================================
    try:
        sc = _outcomes.outcomes(days=score_window_days)
        s_merged = sc.get("merged", 0)
        s_closed = sc.get("closed", 0)
        s_merged_rec = sc.get("merged_records", [])
        s_closed_rec = sc.get("closed_records", [])
    except Exception:
        s_merged = s_closed = 0
        s_merged_rec = s_closed_rec = []
    score_rows: list[list[str]] = []
    window = f"~{score_window_days}d"
    total = s_merged + s_closed
    if total:
        score_rows.append([
            "merge rate", window,
            f"{100 * s_merged // total}% ({s_merged}/{total})",
        ])
    combined = [(r.get("closed_at", ""), "merged") for r in s_merged_rec] + \
               [(r.get("closed_at", ""), "closed") for r in s_closed_rec]
    combined.sort(key=lambda x: x[0], reverse=True)
    streak = 0
    last_close_ts = ""
    for ts, kind in combined:
        if kind == "merged":
            streak += 1
        else:
            last_close_ts = ts
            break
    if combined:
        last_close = _parse_ts(last_close_ts)
        if last_close:
            streak_window = "since " + _fmt_age((now - last_close).total_seconds()) + " ago"
        else:
            streak_window = "all-time"  # no close in this window
        score_rows.append([
            "streak", streak_window,
            f"{streak} ✅" if streak else "0 (last was closed)",
        ])
    # Retro takt floor: daily standup cadence. Source is the canonical
    # SOAP one-pager dir via retro_state.most_recent_retro() — distinct
    # from the per-repo params dir (`retro-params/`, formerly `retro/`),
    # which tracks knob history per repo and would give a misleading
    # "fresh" reading on any param tweak. Overdue is a soft signal here;
    # the hard signal would be an andon at 2× the floor.
    last = retro_state.most_recent_retro()
    if last:
        age_s = (now - last.written_at).total_seconds()
        cell = _fmt_age(age_s) + " ago"
        if age_s > 86400:
            cell += " ⚠️ overdue"
        score_rows.append(["last retro", "daily takt", cell])

    if score_rows:
        lines += ["# Wasteboard", "", "```"]
        kw = max(len(r[0]) for r in score_rows)
        ww = max(len(r[1]) for r in score_rows)
        for k, w, v in score_rows:
            lines.append(f"{k.ljust(kw)}   {w.ljust(ww)}   {v}")
        lines += ["```", ""]

    try:
        org_data = org_state.state()
    except Exception:
        org_data = {"orgs": {}}

    # ====================================================================
    # 0. DOWNSTREAM QUEUE — age histogram of open PRs (waiting on reviewers)
    # ====================================================================
    # Every open PR is consuming a downstream attention slot. The age
    # distribution shows where the queue is piling up. Long right tail
    # = many slots stuck on stale PRs we should give up on.
    open_pr_ages: list[dt.datetime] = []
    for prs in org_data.get("orgs", {}).values():
        for p in prs:
            t = _parse_ts(p.get("updated_at", "")) or _parse_ts(p.get("created_at", ""))
            if t:
                open_pr_ages.append(t)
    if open_pr_ages:
        buckets = _age_histogram_30d(open_pr_ages, now)
        lines += [f"## Age distribution of {len(open_pr_ages)} open PRs", ""]
        lines += _render_age_spark("days since last activity", buckets)

# ====================================================================
    # 2. BAD ORG PICKS — orgs with poor acceptance over the lookback
    # ====================================================================
    try:
        oc = _outcomes.outcomes(days=pick_window_days)
        merged_records = oc.get("merged_records", [])
        closed_records = oc.get("closed_records", [])
    except Exception:
        merged_records = closed_records = []
    org_stats: dict[str, dict[str, int]] = defaultdict(
        lambda: {"merged": 0, "closed": 0})
    for r in merged_records:
        org_stats[org_state.org_of(r.get("repo", ""))]["merged"] += 1
    for r in closed_records:
        org_stats[org_state.org_of(r.get("repo", ""))]["closed"] += 1
    own_user = org_data.get("user", "")
    good: list[tuple[str, int]] = []
    bad: list[tuple[str, int]] = []
    for org, s in org_stats.items():
        if not org or org == own_user:
            continue
        if s["merged"] > 0:
            good.append((org, s["merged"]))
        attempts = s["merged"] + s["closed"]
        if attempts >= 2 and s["merged"] == 0:
            bad.append((org, s["closed"]))
    good.sort(key=lambda x: -x[1])
    bad.sort(key=lambda x: -x[1])
    good, bad = good[:10], bad[:10]
    if good or bad:
        lines += [f"## Org picks — since the tinygrad ban ({pick_window_days}d)",
                  "", "```"]
        good_cells = [f"{o} ({n})" for o, n in good]
        bad_cells = [f"{o} ({n})" for o, n in bad]
        gw = max((len(c) for c in good_cells), default=0)
        gw = max(gw, len("Merged"))
        bw = max((len(c) for c in bad_cells), default=0)
        bw = max(bw, len("Closed"))
        lines.append(f"{'Merged'.ljust(gw)}     {'Closed'.ljust(bw)}")
        for i in range(max(len(good_cells), len(bad_cells))):
            g = good_cells[i] if i < len(good_cells) else ""
            b = bad_cells[i] if i < len(bad_cells) else ""
            lines.append(f"{g.ljust(gw)}     {b.ljust(bw)}".rstrip())
        lines += ["```", ""]

    # ====================================================================
    # 3. STUCK INTERNAL WIP — inbox items older than --wip-stuck days
    # ====================================================================
    wip_cutoff = now - dt.timedelta(days=wip_stuck_days)
    stuck_rows: list[list[str]] = []
    for station in STATIONS:
        try:
            st = inbox_states(station)
        except Exception:
            continue
        items = st.get("queued", []) + st.get("in_flight", [])
        stuck = []
        for m in items:
            t = _parse_ts(m.get("ts", ""))
            if t and t < wip_cutoff:
                stuck.append((t, m))
        if stuck:
            stuck.sort(key=lambda x: x[0])
            oldest_age = _fmt_age((now - stuck[0][0]).total_seconds())
            stuck_rows.append([station, str(len(stuck)), oldest_age])
    if stuck_rows:
        lines += [f"## Stuck internal WIP — inbox items ≥{wip_stuck_days}d old", ""]
        lines += _render_table(["station", "stuck", "oldest"], stuck_rows,
                               aligns=["l", "r", "r"])

    # ====================================================================
    # GITHUB API utilization — live %-of-rate-limit, resets hourly
    # ====================================================================
    api_rows: list[list[str]] = []
    try:
        import subprocess as _sp
        import time as _time
        # TTL via sweep.cache_policy. The `reset` timestamps are
        # absolute (countdown computed from now, not from cached
        # snapshot), so caching only stales the `used` count — at
        # most RATE_LIMIT_TTL of pipeline activity, invisible in
        # the % display. TUI refreshes every 5s; cache shields the
        # ~0.3s subprocess on most of those.
        from sweep.cache_policy import RATE_LIMIT_TTL
        cache_path = Path.home() / ".sweep" / "cache" / "gh_rate_limit.json"
        data = None
        if cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text())
                if _time.time() - cached.get("fetched_at", 0) < RATE_LIMIT_TTL:
                    data = cached.get("resources")
            except (json.JSONDecodeError, OSError):
                pass
        if data is None:
            raw = _sp.run(
                ["gh", "api", "rate_limit"],
                capture_output=True, text=True, timeout=5,
            )
            if raw.returncode == 0:
                parsed = json.loads(raw.stdout)
                data = parsed.get("resources", {})
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps({
                    "resources": data, "fetched_at": _time.time(),
                }))
        if data:
            # Window length per resource (seconds). Search is 1-minute,
            # the rest are 1-hour rolling.
            window_s = {"core": 3600, "graphql": 3600, "search": 60,
                        "code_scanning_upload": 3600,
                        "integration_manifest": 3600, "source_import": 3600}
            for name in ("core", "search", "graphql"):
                r = data.get(name) or {}
                used = r.get("used", 0)
                limit = r.get("limit", 0)
                reset = r.get("reset", 0)
                if not limit:
                    continue
                pct = 100 * used / limit
                secs = max(0, int(reset - _time.time()))
                resets_in = f"{secs // 60}m {secs % 60}s"
                # Project where we'll land at reset if we keep burning at
                # the current rate. Highlights the trajectory — 6% now
                # can be 80% by reset if you're hot.
                w = window_s.get(name, 3600)
                elapsed = max(1, w - secs)
                projected = used * w / elapsed
                proj_pct = 100 * projected / limit
                proj_cell = f"{proj_pct:.0f}%"
                if proj_pct >= 100:
                    proj_cell += " ⚠️"
                api_rows.append([name, f"{pct:.0f}%", proj_cell, resets_in])
    except Exception:
        pass
    if api_rows:
        lines += ["## GitHub API utilization", ""]
        counters = observe.counters_all()
        hits = sum(v for k, v in counters.items() if k.startswith("gh_hit:"))
        misses = sum(v for k, v in counters.items() if k.startswith("gh_miss:"))
        if hits + misses:
            cache_pct = 100 * hits // (hits + misses)
            lines += ["```", f"cache hit rate   {cache_pct}%", "```", ""]
        lines += _render_table(
            ["resource", "now", "at reset", "resets in"], api_rows,
            aligns=["l", "r", "r", "r"])

    # Disk pressure — worktree clones accumulate forever (no GC today),
    # so the operator needs a heads-up before the volume fills. Two
    # numbers: how much the substrate's clones are eating, and how
    # much room is left on the volume they live on.
    try:
        disk_lines = _render_disk_pressure()
        if disk_lines:
            lines += disk_lines
    except Exception:
        pass

    # If nothing showed up, say so
    if len(lines) <= 2:
        lines.append("_no waste detected — kanban full, slots fresh, no stuck WIP_")

    print("\n".join(lines).rstrip())


def _human_bytes(n: int) -> str:
    """Render bytes as B / KB / MB / GB. Sticks to one decimal at GB
    so the eye can compare across reads."""
    for unit, divisor in (("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)):
        if n >= divisor:
            return f"{n / divisor:.1f}{unit}"
    return f"{n}B"


_DISK_STATE = Path.home() / ".sweep" / "state" / "disk.json"


def _read_disk_bytes(path: Path) -> int | None:
    """Read the worker-written disk-usage stamp. Display-only — no
    subprocess, no fallback du. If the worker hasn't written it yet,
    return None and the display omits the section. The worker's
    refresher (sift tick) is responsible for keeping it current; if
    it stops, the missing section is the andon signal."""
    if not _DISK_STATE.exists():
        return None
    try:
        data = json.loads(_DISK_STATE.read_text())
        entry = data.get(str(path))
        if entry:
            return int(entry["bytes"])
    except (json.JSONDecodeError, OSError, ValueError, KeyError):
        pass
    return None


def _render_disk_pressure() -> list[str]:
    """Two numbers: worktree-dir bytes used + free bytes on the volume
    they live on. Anything fancier (per-repo breakdown, GC suggestions)
    can land later; the floor signal is just 'is this getting close to
    a problem.'"""
    import shutil
    wt_root = Path.home() / ".sweep" / "worktrees"
    used = _read_disk_bytes(wt_root)
    if used is None:
        return []
    try:
        total, _, free = shutil.disk_usage(str(wt_root.parent))
    except OSError:
        return []
    pct_free = 100 * free / total if total else 0
    flag = " ⚠️" if pct_free < 10 else ""
    return [
        "## Disk pressure",
        "",
        "```",
        f"worktrees   {_human_bytes(used)}",
        f"free        {_human_bytes(free)}  ({pct_free:.0f}% of volume){flag}",
        "```",
        "",
    ]


def register(app: typer.Typer) -> None:
    app.add_typer(waste_app, name="waste")
