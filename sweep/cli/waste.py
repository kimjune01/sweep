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


def _spark_floored(counts: list[int], *, peak: int | None = None) -> str:
    """Sparkline that never hides nonzero counts and shows zeros as '·'.

    When ``peak`` is supplied, bars are scaled to that external maximum
    instead of the list's own max — useful when two sparklines need
    visual magnitude parity (e.g. Merged vs Closed: a count of 2 on one
    line should not look as tall as a count of 4 on the other).
    """
    scale_peak = peak if peak is not None else max(counts) or 1
    if scale_peak <= 0:
        scale_peak = 1
    out = []
    for c in counts:
        if c == 0:
            out.append("·")
        else:
            level = max(1, min(8, int(round(c * 8 / scale_peak))))
            out.append(_SPARK[level])
    return "".join(out)


def _render_age_spark(label: str, buckets: list[int]) -> list[str]:
    """30-char sparkline with axis hints. Empty if no data.

    Uses inline-backtick spans (not fenced blocks) so the bars render
    in the terminal's normal foreground color instead of the muted
    code-block tone. Most renderers keep inline code monospace +
    default-color — which is what we want for these alignment-sensitive
    one-liners.
    """
    if not buckets or sum(buckets) == 0:
        return []
    buckets = list(reversed(buckets))  # past on the left, present on the right
    spark = _spark_floored(buckets)
    # Single-line layout: spark on the left, axis labels inline on the
    # right. Saves a vertical line and keeps the eye in one row.
    return [f"29d   `{spark}`   today", ""]


def _render_table(headers: list[str], rows: list[list[str]],
                  aligns: list[str] | None = None) -> list[str]:
    """Render a markdown pipe-table. aligns is 'l' or 'r' per col.

    Markdown renderers style these as proper tables (full color, not
    the muted code-block treatment) and they degrade gracefully to
    plain text when no renderer is involved.
    """
    aligns = aligns or (["l"] * len(headers))
    sep_row = ["---:" if a == "r" else ":---" for a in aligns]
    def row(cells: list[str]) -> str:
        return "| " + " | ".join(str(c) for c in cells) + " |"
    out: list[str] = [row(headers), row(sep_row)]
    for r in rows:
        out.append(row(r))
    out.append("")
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
        lines += ["# Wasteboard", ""]
        lines += _render_table(
            ["metric", "window", "value"], score_rows,
            aligns=["l", "l", "l"],
        )

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
        lines += [f"## Org picks — since the tinygrad ban ({pick_window_days}d)", ""]
        # Shared peak so Merged vs Closed bars are vertically
        # comparable — a count of 2 must not look as tall as a 4.
        shared_peak = max(
            max((n for _, n in good), default=0),
            max((n for _, n in bad), default=0),
            1,
        )
        if good:
            counts = [n for _, n in good]
            lines.append(
                f"Merged   {_spark_floored(counts, peak=shared_peak)}  "
                f"(top {len(counts)}, max {counts[0]})"
            )
        if bad:
            counts = [n for _, n in bad]
            lines.append(
                f"Closed   {_spark_floored(counts, peak=shared_peak)}  "
                f"(top {len(counts)}, max {counts[0]})"
            )
        lines.append("")

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
                api_rows.append((name, pct, proj_pct, resets_in))
    except Exception:
        pass
    if api_rows:
        counters = observe.counters_all()
        hits = sum(v for k, v in counters.items() if k.startswith("gh_hit:"))
        misses = sum(v for k, v in counters.items() if k.startswith("gh_miss:"))
        if hits + misses:
            cache_pct = 100 * hits // (hits + misses)
            heading = f"## GitHub API ({cache_pct}% cache hit)"
        else:
            heading = "## GitHub API"
        # One-liner: each resource as `name bar pct→projected%` cluster,
        # bullet-separated. Reset time as suffix. Bar uses the projected
        # value (the quantity that determines whether we run out).
        parts: list[str] = []
        soonest_reset = ""
        for name, pct, proj_pct, resets_in in api_rows:
            warn = " ⚠️" if proj_pct >= 100 else ""
            parts.append(
                f"{name} `{_mini_bar(proj_pct)}` {pct:.0f}%→{proj_pct:.0f}%{warn}"
            )
            if not soonest_reset:
                soonest_reset = resets_in
        suffix = f"  (reset in {soonest_reset})" if soonest_reset else ""
        lines += [heading, "", "  ·  ".join(parts) + suffix, ""]

    # SaaS quota (Claude Code's 5h subscription window) read from the
    # cached `/usage` probe; freshness tag tells the operator whether
    # the number is current. Anthropic API spend (separately billed in
    # dollars) read from the attestation chain.
    # API spend is now inlined into the Claude Code quota line via
    # `_inline_anthropic_api_spend`. The separate `_render_quota_burn`
    # panel was kept for table-shape per-model breakdown — drop it
    # here so the wasteboard reads as one cost surface.
    try:
        block = _render_claude_saas_quota()
        if block:
            lines += block
    except Exception:
        pass

    # Line stoppage — total downtime + halt count over a window, plus
    # the current stoppage age if any actor is halted right now. The
    # operator's eye signal: "have I been letting halts sit?"
    try:
        stop_lines = _render_stoppage()
        if stop_lines:
            lines += stop_lines
    except Exception:
        pass

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


# Rough Anthropic API prices (USD per million tokens). Approximate;
# only used for the wasteboard's "you're burning ~$X" hint, not for
# billing. Pricing drifts; if a model isn't listed, we skip the cost
# line for that model rather than guess.
#
# Cache writes are billed at 1.25× the input rate; cache reads at 0.1×.
# These multipliers are applied to the input price below — keep them in
# sync if Anthropic changes the cache pricing structure.
_API_PRICE_PER_MTOK: dict[str, tuple[float, float]] = {
    # nick: (input $/MTok, output $/MTok)
    "sonnet": (3.0, 15.0),
    "haiku":  (0.80, 4.0),
    "opus":   (15.0, 75.0),
}
_CACHE_WRITE_MULT = 1.25
_CACHE_READ_MULT = 0.10


def _render_quota_burn() -> list[str]:
    """Wasteboard surface for the part of LLM spend we can actually
    measure precisely — Anthropic API tokens (billed in real dollars).
    Aggregated from the attestation chain over the last 5h.

    Claude Code SaaS quota (5h subscription window) is deliberately
    NOT surfaced here. Raw subprocess call count is not a meaningful
    proxy for percent-of-quota-used; only the `/usage` panel knows
    the real number, and that's a pty-driven probe (see usage_probe.py)
    that's currently dep-blocked. Until the probe is reliable, the
    operator's eyeball check via `/usage` is the source of truth for
    the SaaS budget.
    """
    import datetime as _dt

    # 7d window. 24h was the previous setting; it hid the $300 cache-
    # creation burn from 2026-05-16 because all spend was >24h old by
    # the time the operator looked. 7d aligns with billing-cycle
    # awareness and catches sporadic-but-expensive days.
    LOOKBACK_HOURS = 24 * 7
    now = _dt.datetime.now(_dt.timezone.utc)
    cutoff_iso = (now - _dt.timedelta(hours=LOOKBACK_HOURS)).isoformat()

    # Anthropic-only filter: substrate also records codex/gemini
    # subprocess calls (for unified accounting) but those are billed
    # via Claude Code subscription, not API dollars. Operator only
    # cares about real $$ spend here, which is Anthropic-direct.
    from sweep import attestations, models
    anthropic_nicks = {
        nick for nick, info in models.REGISTRY.items()
        if info.provider == "anthropic"
    }
    api_rows: dict[str, dict] = {}
    api_cost = 0.0
    api_in = 0
    api_out = 0
    api_cache_write = 0
    api_cache_read = 0
    try:
        with attestations._conn() as conn:  # type: ignore[attr-defined]
            cur = conn.execute(
                "SELECT model_nick, input_tokens, output_tokens, "
                "cache_creation_input_tokens, cache_read_input_tokens "
                "FROM calls WHERE ts >= ?", (cutoff_iso,),
            )
            for nick, inp, out, cw, cr in cur.fetchall():
                if nick not in anthropic_nicks:
                    continue
                row = api_rows.setdefault(nick, {
                    "calls": 0, "input": 0, "output": 0,
                    "cache_write": 0, "cache_read": 0,
                })
                row["calls"] += 1
                row["input"] += inp or 0
                row["output"] += out or 0
                row["cache_write"] += cw or 0
                row["cache_read"] += cr or 0
                api_in += inp or 0
                api_out += out or 0
                api_cache_write += cw or 0
                api_cache_read += cr or 0
                price = _API_PRICE_PER_MTOK.get(nick)
                if price:
                    api_cost += (
                        (inp or 0) * price[0]
                        + (out or 0) * price[1]
                        + (cw or 0) * price[0] * _CACHE_WRITE_MULT
                        + (cr or 0) * price[0] * _CACHE_READ_MULT
                    ) / 1_000_000
    except Exception:
        return []

    if not api_rows:
        # Always-visible zero state. Operator should see "we checked
        # and there's nothing" rather than nothing at all — absence of
        # the panel is ambiguous (could mean broken, could mean zero).
        return [
            f"## Anthropic API spend (last {LOOKBACK_HOURS}h)",
            "",
            "$0.00 — no Anthropic API calls in window "
            "(substrate currently runs on Claude Code subscription)",
            "",
        ]

    rows: list[list[str]] = []
    for nick in sorted(api_rows):
        r = api_rows[nick]
        price = _API_PRICE_PER_MTOK.get(nick)
        nick_cost = (
            (
                r["input"] * price[0]
                + r["output"] * price[1]
                + r["cache_write"] * price[0] * _CACHE_WRITE_MULT
                + r["cache_read"] * price[0] * _CACHE_READ_MULT
            ) / 1_000_000
            if price else None
        )
        rows.append([
            nick, str(r["calls"]),
            _human_tokens(r["input"]), _human_tokens(r["output"]),
            _human_tokens(r["cache_write"]), _human_tokens(r["cache_read"]),
            f"${nick_cost:.2f}" if nick_cost is not None else "—",
        ])
    # totals row for the eye
    total_cost_cell = f"${api_cost:.2f}" if api_cost > 0 else "—"
    rows.append([
        "total", str(sum(r["calls"] for r in api_rows.values())),
        _human_tokens(api_in), _human_tokens(api_out),
        _human_tokens(api_cache_write), _human_tokens(api_cache_read),
        total_cost_cell,
    ])
    return [f"## Anthropic API spend (last {LOOKBACK_HOURS}h)", ""] + _render_table(
        ["model", "calls", "in", "out", "cache_w", "cache_r", "cost"], rows,
        aligns=["l", "r", "r", "r", "r", "r", "r"],
    )


def _render_bar_histogram(rows: list[tuple[str, int]],
                          *, max_bar_width: int = 24) -> list[str]:
    """Two-column markdown table: label on the left, ASCII bar + count
    on the right. Bars are scaled to the row with the largest count
    (the longest bar = max_bar_width). Renders as a real markdown
    table so renderers style it normally (no fenced-block gray).
    """
    if not rows:
        return []
    peak = max(n for _, n in rows) or 1
    table_rows: list[list[str]] = []
    for label, n in rows:
        bar_len = max(1, round(n * max_bar_width / peak))
        bar = "█" * bar_len
        table_rows.append([label, f"{bar} {n}"])
    return _render_table(["org", ""], table_rows, aligns=["l", "l"]) + [""]


def _render_claude_saas_quota() -> list[str]:
    """Show cached Claude Code /usage percents with a freshness tag.
    Reads ~/.sweep/control/claude_usage.json (written by the usage
    poller). Renders nothing if there's no cache yet — the operator
    sees "API spend" alone until the probe lands a parseable read.
    """
    import datetime as _dt
    cache = Path.home() / ".sweep" / "control" / "claude_usage.json"
    if not cache.exists():
        return []
    try:
        data = json.loads(cache.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    session = data.get("session_pct")
    week = data.get("week_pct")
    if session is None and week is None:
        return []
    ts = data.get("ts", "")
    age_str = "?"
    try:
        # cache ts may be "+00:00" or "+0000"; fromisoformat handles
        # the former but not the latter on 3.11-; normalize.
        norm = ts.replace("+0000", "+00:00")
        cache_ts = _dt.datetime.fromisoformat(norm)
        age_s = (_dt.datetime.now(cache_ts.tzinfo) - cache_ts).total_seconds()
        age_str = _fmt_age(age_s)
    except Exception:
        pass
    parts: list[str] = []
    if session is not None:
        parts.append(f"session `{_mini_bar(float(session))}` {session}%")
    if week is not None:
        parts.append(f"week `{_mini_bar(float(week))}` {week}%")
    # Anthropic API spend inline — same panel, single line. The API
    # bill is part of "how am I spending on LLMs right now"; splitting
    # it into a separate section forced the operator to track two
    # places. Co-located here, the SaaS-quota + $$ -spend reads as one
    # cost surface.
    parts.append(_inline_anthropic_api_spend())
    # Codex usage from ~/.codex/sessions/<today>/*.jsonl. Same panel
    # for the same reason: the operator's question is "what am I
    # burning across all LLM channels right now?", not per-provider.
    codex_line = _inline_codex_quota()
    if codex_line:
        parts.append(codex_line)
    return [
        f"## LLM quota  ({age_str} ago)",
        "",
        "  ·  ".join(parts),
        "",
    ]


def _inline_codex_quota() -> str:
    """One-bullet summary of codex usage from local session rollouts.
    Walks today's ~/.codex/sessions/YYYY/MM/DD/*.jsonl files, sums
    tokens, surfaces the latest rate-limit reading. Returns empty
    string if no codex sessions today (operator using only Claude)."""
    import datetime as _dt
    import glob as _glob
    today = _dt.date.today().strftime("%Y/%m/%d")
    pattern = str(Path.home() / ".codex" / "sessions" / today / "*.jsonl")
    files = sorted(_glob.glob(pattern))
    if not files:
        return ""
    total_in = total_out = 0
    last_rl = None
    n_sessions = 0
    for f in files:
        sess_tc = None
        try:
            with open(f) as fh:
                for line in fh:
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    payload = d.get("payload") or {}
                    if (d.get("type") == "event_msg"
                            and payload.get("type") == "token_count"):
                        sess_tc = payload
        except OSError:
            continue
        if sess_tc and sess_tc.get("info"):
            n_sessions += 1
            t = sess_tc["info"].get("total_token_usage") or {}
            total_in += t.get("input_tokens", 0)
            total_out += t.get("output_tokens", 0)
            last_rl = sess_tc.get("rate_limits") or last_rl
    if n_sessions == 0:
        return ""
    rl_part = ""
    if last_rl:
        p = last_rl.get("primary") or {}
        if "used_percent" in p:
            pct = float(p.get("used_percent", 0))
            rl_part = f" 5h `{_mini_bar(pct)}` {pct:.0f}%"
    return f"codex ({n_sessions} sess) in={_human_tokens(total_in)}{rl_part}"


def _inline_anthropic_api_spend(hours: int = 168) -> str:
    """One-bullet summary of Anthropic-direct API spend over a window.
    Used by `_render_claude_saas_quota` to co-locate $$ spend with
    SaaS-quota burn. Returns a single short string; never multi-line.

    Default 168h (7d) catches bursty days that fall outside a 24h pane
    — the 2026-05-16 cache-creation burn went unseen by a 24h panel
    because nothing was happening when the operator looked. Cache
    creation and read tokens are folded into the cost (1.25× and 0.10×
    input rate respectively) so the bullet matches the actual bill."""
    import datetime as _dt
    from sweep import attestations, models
    anthropic_nicks = {
        nick for nick, info in models.REGISTRY.items()
        if info.provider == "anthropic"
    }
    cutoff_iso = (_dt.datetime.now(_dt.timezone.utc)
                  - _dt.timedelta(hours=hours)).isoformat()
    cost = 0.0
    try:
        with attestations._conn() as conn:  # type: ignore[attr-defined]
            for nick, inp, out, cw, cr in conn.execute(
                "SELECT model_nick, input_tokens, output_tokens, "
                "cache_creation_input_tokens, cache_read_input_tokens "
                "FROM calls WHERE ts >= ?", (cutoff_iso,)).fetchall():
                if nick not in anthropic_nicks:
                    continue
                price = _API_PRICE_PER_MTOK.get(nick)
                if price:
                    cost += (
                        (inp or 0) * price[0]
                        + (out or 0) * price[1]
                        + (cw or 0) * price[0] * _CACHE_WRITE_MULT
                        + (cr or 0) * price[0] * _CACHE_READ_MULT
                    ) / 1_000_000
    except Exception:
        return f"API ({hours}h) —"
    label = f"{hours//24}d" if hours % 24 == 0 else f"{hours}h"
    return f"API ({label}) ${cost:.2f}"


def _mini_bar(pct: float, width: int = 6) -> str:
    """Short bar for inline single-line summaries. Same eighths-glyph
    palette as `_pct_bar` so it composes visually with the longer
    bar in tabular sections."""
    return _pct_bar(pct, width=width)


def _pct_bar(pct: float, width: int = 20) -> str:
    """Filled-vs-dithered percent bar in the /usage style:
    `█` for the used fraction, `░` for the remaining. Eye reads
    "how much of the whole is consumed" at a glance. Same glyph
    pair across panels so GitHub API, Claude quota, and disk
    pressure all visually compose.

    No fractional eighths and no saturation glyph — the caller
    surfaces ⚠️ when a cap is hit; the bar stays unambiguous as
    a ratio."""
    pct = max(0.0, min(100.0, pct))
    filled = round((pct / 100.0) * width)
    return "█" * filled + "░" * (width - filled)


def _human_tokens(n: int) -> str:
    """Render token counts as K/M with one decimal — eye-comparable
    across two-orders-of-magnitude ranges that LLM accounting hits."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _render_stoppage(window_minutes: int = 60) -> list[str]:
    """Compute and render line-stoppage over a recent window.

    In substrate-time, 24h is geological — most cards cycle in
    minutes, halts that aren't fixed within an hour are anomalies.
    Default window is the actionable one: last 60 minutes, with the
    rolling line at 1-minute resolution. Going older (24h, 7d) is
    archive-reading, not operator intervention.

    Pairs `andon_recorded` (halt) with `andon_cleared` (resume) events
    from events.jsonl; computes per-halt durations; sums to total
    downtime in window. Also surfaces current downtime if any marker
    file is still present (operator hasn't cleared yet).

    Reads:
      uptime%  = 1 - (total_downtime / window) — the OEE "availability"
      n_halts  = count of halts that started in window
      now      = age of oldest currently-held marker, if any

    Always renders (never returns []) so the panel-absence ambiguity
    doesn't bite — same shape as the Anthropic API spend zero-state."""
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc)
    cutoff = now - _dt.timedelta(minutes=window_minutes)
    window_s = window_minutes * 60.0
    events_path = Path.home() / ".sweep" / "events.jsonl"

    # Build halt periods: walk events, pair (record → clear) per actor.
    # An unpaired record (still open at end) is a currently-active halt
    # whose end-time is "now."
    open_starts: dict[str, _dt.datetime] = {}
    periods: list[tuple[str, _dt.datetime, _dt.datetime]] = []
    n_halts = 0
    if events_path.exists():
        try:
            for line in events_path.read_text().splitlines():
                if not line.strip():
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                kind = e.get("kind", "")
                if kind not in ("andon_recorded", "andon_cleared"):
                    continue
                actor = e.get("actor", "?")
                ts_s = e.get("ts", "")
                try:
                    ts = _dt.datetime.fromisoformat(ts_s)
                except ValueError:
                    continue
                if kind == "andon_recorded":
                    open_starts[actor] = ts
                    if ts >= cutoff:
                        n_halts += 1
                else:  # andon_cleared
                    start = open_starts.pop(actor, None)
                    if start is None:
                        continue
                    end = ts
                    # Clip to window so a halt straddling cutoff still
                    # contributes only its in-window slice.
                    period_start = max(start, cutoff)
                    period_end = min(end, now)
                    if period_end > period_start:
                        periods.append((actor, period_start, period_end))
        except OSError:
            pass

    # Marker-file pass — the file is the truth for "halted right now."
    # If a marker exists but no `andon_recorded` event matched (e.g.
    # pre-instrumentation halt, or a watchdog that wrote before the
    # event hook landed), seed it into `open_starts` so the uptime
    # calculation reflects the live halt. Without this seed, panel
    # shows "uptime 100% · halted now 1" — inconsistent.
    andon_dir = Path.home() / ".sweep" / "control" / "andon"
    current_halts: list[tuple[str, float]] = []
    if andon_dir.exists():
        for f in andon_dir.glob("*.json"):
            try:
                d = json.loads(f.read_text())
                ts = _dt.datetime.fromisoformat(d.get("ts", ""))
                age = (now - ts).total_seconds()
                actor = d.get("actor", f.stem)
                current_halts.append((actor, age))
                # Seed if event-pair missed this marker.
                if actor not in open_starts:
                    open_starts[actor] = ts
            except Exception:
                continue

    # Currently-open halts contribute (now - start), clipped to window.
    for actor, start in open_starts.items():
        period_start = max(start, cutoff)
        if now > period_start:
            periods.append((actor, period_start, now))

    total_down = sum((e - s).total_seconds() for _, s, e in periods)
    uptime_pct = 100.0 * (1.0 - total_down / window_s) if window_s > 0 else 100.0
    uptime_pct = max(0.0, min(100.0, uptime_pct))

    parts: list[str] = []
    parts.append(f"uptime `{_mini_bar(uptime_pct)}` {uptime_pct:.1f}%")
    parts.append(f"halts {n_halts}")
    if current_halts:
        oldest = max(a for _, a in current_halts)
        actors = ", ".join(sorted(a for a, _ in current_halts))
        flag = " ⚠️"
        parts.append(f"halted now {len(current_halts)} ({actors}) {_fmt_age(oldest)}{flag}")
    else:
        parts.append("halted now 0")

    # Rolling per-minute uptime spark — each cell is one minute,
    # width matches the window. At 60min the spark is 60 cells wide,
    # operator-readable on one line. Dips mark recorded downtime
    # minutes; the rightmost cell is now-1min, leftmost is the
    # window's oldest minute. New minutes append right; oldest
    # falls off left as time advances.
    minute_buckets = _uptime_minutes(periods, open_starts, now,
                                      minutes=window_minutes)
    spark = _render_uptime_spark(minute_buckets)

    return [
        f"## Line stoppage (last {window_minutes}m)",
        "",
        "  ·  ".join(parts),
        "",
        f"`{spark}`",
        "",
    ]


def _uptime_minutes(
    periods: list,
    open_starts: dict,
    now,
    minutes: int = 60,
) -> list[float]:
    """Return `minutes` uptime fractions, oldest → newest. Each
    entry is `1 - downtime_in_minute / 60`. Periods crossing minute
    boundaries get split at the top-of-minute."""
    import datetime as _dt
    minute_start = (now - _dt.timedelta(minutes=minutes - 1)).replace(
        second=0, microsecond=0,
    )
    downtime_per_minute: list[float] = [0.0] * minutes

    def _accum(start, end):
        s = max(start, minute_start)
        e = min(end, now)
        if e <= s:
            return
        cur = s
        while cur < e:
            top = cur.replace(second=0, microsecond=0)
            idx = int((top - minute_start).total_seconds() // 60)
            next_top = top + _dt.timedelta(minutes=1)
            slice_end = min(next_top, e)
            secs = (slice_end - cur).total_seconds()
            if 0 <= idx < minutes:
                downtime_per_minute[idx] += secs
            cur = slice_end

    for _actor, s, e in periods:
        _accum(s, e)
    for _actor, s in open_starts.items():
        _accum(s, now)

    return [max(0.0, 1.0 - d / 60.0) for d in downtime_per_minute]


def _render_uptime_spark(uptime_fracs: list[float]) -> str:
    """Render an uptime sparkline using the eighths palette. 1.0 = █,
    0 = blank. Color-blind safe (no color, just glyph height).

    Status-page convention: each cell is one day. A row of all-█ =
    no recorded downtime. Visible dips draw the eye to outage days."""
    eighths = " ▁▂▃▄▅▆▇█"
    out: list[str] = []
    for frac in uptime_fracs:
        idx = max(0, min(8, int(round(frac * 8))))
        out.append(eighths[idx])
    return "".join(out)


def _render_disk_pressure() -> list[str]:
    """Two-bar one-liner: total volume fill + sweep's share of the
    space currently available to it.

    First bar: volume usage as %% of disk size (system view).
    Second bar: sweep's footprint as %% of the volume's available
    space (the operator's lever: this is what we control with
    broom/cache prune/worktree evict).

    Same `_pct_bar` glyph as GitHub API + LLM quota so the operator's
    eye can compare pressure across all three at once."""
    import shutil
    wt_root = Path.home() / ".sweep" / "worktrees"
    bc_root = Path.home() / ".sweep" / "build-cache"
    repos_root = Path.home() / ".sweep" / "repos"
    try:
        total, _, free = shutil.disk_usage(str(wt_root.parent))
    except OSError:
        return []
    used_total = total - free
    pct_volume = 100 * used_total / total if total else 0
    vol_flag = " ⚠️" if pct_volume >= 90 else ""

    sweep_bytes = 0
    for p in (wt_root, bc_root, repos_root):
        b = _read_disk_bytes(p)
        if b is not None:
            sweep_bytes += b
    available = free + sweep_bytes  # what we COULD use if we cleared ourselves
    pct_sweep = 100 * sweep_bytes / available if available else 0
    sweep_flag = " ⚠️" if pct_sweep >= 80 else ""

    line = (
        f"volume `{_pct_bar(pct_volume)}` {pct_volume:.0f}%{vol_flag} "
        f"({_human_bytes(used_total)}/{_human_bytes(total)})"
        f"  ·  sweep `{_pct_bar(pct_sweep)}` {pct_sweep:.0f}%{sweep_flag} "
        f"({_human_bytes(sweep_bytes)} of {_human_bytes(available)} avail)"
        f"  ·  `sweep broom disk` to reclaim"
    )
    return ["## Disk pressure", "", line, ""]


def register(app: typer.Typer) -> None:
    app.add_typer(waste_app, name="waste")
