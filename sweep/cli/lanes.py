"""`sweep lanes` — swim lanes, no metrics. Just PRs by station.

Renders two adjacent views: the swim-lane table (point-in-time
inventory per station) and the **leakdog** table (flow accounting
across interfaces over a recent window). Together they answer:
"where is each PR right now" + "where are items getting lost between
stations." Target is zero unaccounted leaks; every drop should be
explained by an explicit decision event.
"""

from __future__ import annotations

import datetime as dt
import json
from collections import Counter
from pathlib import Path

import typer

from sweep.inbox_state import inbox_states


# Pipeline order, left → right:
#   triaged     — LLM (/triage output): issues scored, awaiting investigation
#   investigate — LLM (/investigate): root-cause + fix branch
#   qa          — LLM, runs gates
#   drip        — LLM, paces pushes
#   in review   — reviewer holds the ball (retro/wait inbox)
#   respondable — ball back to you (human) after reviewer engages
STATIONS = [
    ("triaged",     "triaged"),
    ("investigate", "investigate"),
    ("qa",          "qa"),
    ("respond",     "respond"),
    ("retro",       "in review"),
    ("respondable", "respondable"),
]


def register(app: typer.Typer) -> None:
    app.command("lanes")(lanes)


def render_lanes(height: int = 7) -> list[str]:
    """Build the swim-lane lines without printing — shared with
    `sweep cockpit` so the conveyor section uses the same rendering as the
    standalone `sweep lanes` command. Returns the full markdown block."""
    cols = STATIONS

    items: dict[str, list[str]] = {}
    counts: dict[str, int] = {}
    for actor, _label in cols:
        s = inbox_states(actor)
        in_flight_ids = {m.get("msg_id") for m in s["in_flight"]}
        msgs = sorted(s["queued"] + s["in_flight"], key=lambda x: x.get("ts", ""))
        # Retro is the pr-state wait-bucket audit trail; pr-state
        # appends one entry per poll cycle per PR, so raw len()
        # over-counts. Dedupe to unique (repo, pr) for the header
        # count — the column body still shows individual entries but
        # the header tells the truth about distinct PRs in review.
        if actor == "retro":
            counts[actor] = len({(m.get("repo"), m.get("pr")) for m in msgs})
        else:
            counts[actor] = len(msgs)
        rendered: list[str] = []
        for m in msgs:
            link = (
                f"[{m.get('repo', '?')}#{m.get('pr', '-')}]"
                f"(https://github.com/{m.get('repo', '')}/pull/{m.get('pr', '')})"
            )
            prefix = "✈️ " if m.get("msg_id") in in_flight_ids else ""
            rendered.append(f"{prefix}{link}")
        items[actor] = rendered

    # Truncate each column to `height` rows. Reserve the last row for the
    # truncation indicator when a column has more.
    display: dict[str, list[str]] = {}
    for actor, _label in cols:
        col = items[actor]
        if len(col) <= height:
            display[actor] = col
        else:
            shown = col[: max(0, height - 1)]
            shown.append(f"_… +{len(col) - len(shown)} more_")
            display[actor] = shown

    max_rows = max((len(display[a]) for a, _ in cols), default=0)
    headers = [f"{label} ({counts[a]})" for a, label in cols]

    lines: list[str] = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join("---" for _ in cols) + "|")
    if max_rows == 0:
        lines.append("| " + " | ".join("_empty_" for _ in cols) + " |")
        return lines
    for row in range(max_rows):
        cells = []
        for actor, _label in cols:
            col = display[actor]
            cells.append(col[row] if row < len(col) else " ")
        lines.append("| " + " | ".join(cells) + " |")
    return lines


# ---------------------------------------------------------- leakdog
# Interface accounting. Each row is "items entering interface = items
# continuing + items dropped with a recorded reason." Anything missing
# is a LEAK — leakdog is the watchdog that sniffs out the unaccounted
# losses against the zero-leak target.
#
# Lag tolerance: an item upstream that's younger than the interface's
# lag isn't a leak; it's in flight. Without this, every fresh deposit
# looks like a triage leak.


def _events_for_pr(repo: str, pr: int, *, hours: int = 168) -> list[dict]:
    """All events keyed to (repo, pr) in the last `hours`, oldest first.
    Default 168h = 7d covers the relevant decision window for any item
    currently in a lane. The events.jsonl walk is cheap (<1MB typically);
    cached or indexed only when this becomes the rendering bottleneck."""
    path = Path.home() / ".sweep" / "events.jsonl"
    if not path.exists():
        return []
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
    out: list[dict] = []
    try:
        text = path.read_text()
    except OSError:
        return []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        # `pr` may live under `pr` (PR-side events) or `issue`
        # (issue-side events — sift/tissue/bless). Match either.
        e_repo = e.get("repo", "")
        e_pr = e.get("pr") if e.get("pr") is not None else e.get("issue")
        if e_repo != repo or e_pr != pr:
            continue
        ts = e.get("ts", "")
        try:
            if dt.datetime.fromisoformat(ts) < cutoff:
                continue
        except (ValueError, AttributeError):
            continue
        e["_t"] = dt.datetime.fromisoformat(ts)
        out.append(e)
    out.sort(key=lambda x: x.get("_t"))
    return out


# Compact abbreviations for the provenance chain. Each event kind maps
# to a short token (verbs in present tense, lowercase). Order matters
# in the rendered chain because earliest event is leftmost.
_PROVENANCE_TOKENS: dict[str, callable] = {
    "sift_deposited":       lambda e: "📥sift",
    "triage_decision":      lambda e: f"🔬triage→{(e.get('decision') or '?')[:4]}",
    "investigate_done":     lambda e: ("🛠ship" if e.get("produced_pr")
                                       else ("🤝gated" if e.get("human_gated")
                                       else ("⛔no-fix" if e.get("no_fix")
                                       else "🛠done"))),
    "tissue_card_deposited": lambda e: "🤧tissue?",
    "tissue_drafted":       lambda e: "🤧drafted",
    "tissue_skipped":       lambda e: f"🤧skip:{(e.get('reason') or '?')[:8]}",
    "tissue_posted":        lambda e: "📨posted",
    "tissue_engaged":       lambda e: "💬engaged",
    "tissue_muted":         lambda e: "🔇muted",
    "tissue_post_failed":   lambda e: "❗post-fail",
    "bless_card_deposited": lambda e: "🙏bless?",
    "bless_routed":         lambda e: f"🙏→{(e.get('kind') or '?')[:6]}",
    "immunize_card_deposited": lambda e: "💉immunize?",
    "immunize_redirected":  lambda e: ("💉draft" if e.get("drafted")
                                       else "💉seed"),
    "immunize_skipped":     lambda e: f"💉skip:{(e.get('reason') or '?')[:8]}",
    "pr_state_classified":  lambda e: f"🔀{(e.get('bucket') or '?')[:6]}",
    "qa_converged":         lambda e: f"✅qa:{(e.get('verdict') or '?')[:4]}",
    "respond_done":         lambda e: ("🚀pushed" if e.get("pushed") else "💧noop"),
}


def _ts_compact(now: dt.datetime, t: dt.datetime) -> str:
    """How long ago, short form: 3m / 4h / 2d. The provenance line is
    horizontally dense; full timestamps would crowd it out."""
    secs = (now - t).total_seconds()
    if secs < 60:
        return f"{int(secs)}s"
    if secs < 3600:
        return f"{int(secs // 60)}m"
    if secs < 86400:
        return f"{int(secs // 3600)}h"
    return f"{int(secs // 86400)}d"


def _render_provenance_chain(events: list[dict]) -> str:
    """Format one item's chain. Returns 'P📥 3h → T🔬→inve 2h → I🛠ship 1h'.
    Unknown event kinds are skipped (kept implicit) — the rendered chain
    is opinionated about which events tell the story."""
    if not events:
        return "_no events_"
    now = dt.datetime.now(dt.timezone.utc)
    parts: list[str] = []
    for e in events:
        kind = e.get("kind", "")
        fmt = _PROVENANCE_TOKENS.get(kind)
        if not fmt:
            continue
        try:
            tok = fmt(e)
        except Exception:
            continue
        age = _ts_compact(now, e["_t"])
        parts.append(f"{tok} _{age}_")
    if not parts:
        return "_no decisions_"
    return " → ".join(parts)


def _render_provenance_section(lookback_hours: int = 168) -> list[str]:
    """For every active (repo, pr) across all stations, render its
    provenance chain. Active = items currently in any inbox's queued
    or in-flight state. Items in `done` state aren't rendered (closed
    chains are interesting historically but the kanban view is about
    open work)."""
    from sweep.inbox_state import inbox_states as _is
    stations = [a for a, _ in STATIONS]
    active: dict[tuple, dict] = {}  # (repo, pr) → minimal msg
    for actor in stations:
        s = _is(actor)
        for m in s["queued"] + s["in_flight"]:
            repo = m.get("repo")
            pr = m.get("pr")
            if not repo or pr is None:
                continue
            key = (repo, int(pr))
            active.setdefault(key, {"repo": repo, "pr": int(pr),
                                    "station": actor,
                                    "in_flight": False})
            if m.get("msg_id") in {x.get("msg_id") for x in s["in_flight"]}:
                active[key]["in_flight"] = True
    if not active:
        return []
    lines: list[str] = ["", f"# Provenance — active items (last {lookback_hours//24}d)", ""]
    for (repo, pr), info in sorted(active.items()):
        events = _events_for_pr(repo, pr, hours=lookback_hours)
        chain = _render_provenance_chain(events)
        marker = "✈️ " if info["in_flight"] else ""
        link = f"[{repo}#{pr}](https://github.com/{repo}/issues/{pr})"
        lines.append(f"- {marker}{link} _(in `{info['station']}`)_")
        lines.append(f"  {chain}")
    return lines


def _events_since(hours: int) -> list[dict]:
    path = Path.home() / ".sweep" / "events.jsonl"
    if not path.exists():
        return []
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
    out = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            t = dt.datetime.fromisoformat(e.get("ts", ""))
        except ValueError:
            continue
        if t >= cutoff:
            e["_t"] = t
            out.append(e)
    return out


def _inbox_pending(actor: str) -> int:
    """Count of items currently queued or in-flight at an actor's
    station. These are 'in transit, not leaked' — subtract from raw
    leak counts so slow-processing doesn't look like loss."""
    try:
        s = inbox_states(actor)
        return len(s.get("queued", [])) + len(s.get("in_flight", []))
    except Exception:
        return 0


def render_leakdog(hours: int = 24) -> list[str]:
    """Funnel-balance table over the last `hours`. Returns markdown lines.

    Interfaces:
      sift        → triage       (deposit → triage_decision)
      triage      → investigate  (triage_decision=investigate → investigate_done)
      investigate → drip         (investigate_done(produced_pr) → pr_state_classified)
      pr-state    → qa           (pr_state_classified(bucket=qa) → qa_converged)

    A row's `leak` = `in − (out + screened + still_in_inbox)`. The inbox
    subtraction is what separates real loss from slow processing. Lag
    tolerance still applies to `in` so items too fresh to have been
    processed yet don't get counted."""
    events = _events_since(hours)
    now = dt.datetime.now(dt.timezone.utc)

    def aged(kind: str, lag_minutes: int, pred=lambda e: True) -> int:
        cutoff = now - dt.timedelta(minutes=lag_minutes)
        return sum(1 for e in events
                   if e.get("kind") == kind and e["_t"] < cutoff and pred(e))

    def count(kind: str, pred=lambda e: True) -> int:
        return sum(1 for e in events if e.get("kind") == kind and pred(e))

    # sift → triage: every deposit should trigger a triage_decision
    deposits = aged("sift_deposited", lag_minutes=15)
    triaged_total = count("triage_decision")
    triaged_pending = _inbox_pending("triaged")

    # triage → investigate: only the "investigate" branch flows forward
    triaged_invest = aged("triage_decision", lag_minutes=60,
                          pred=lambda e: e.get("decision") == "investigate")
    triaged_other = count("triage_decision",
                          pred=lambda e: e.get("decision") != "investigate")
    invest_done = count("investigate_done")
    invest_pending = _inbox_pending("investigate")

    # investigate → qa: investigations that produced a PR should flow
    # through to a qa_converged outcome. pr-state is the dispatcher
    # that routes the open PR — bookkeeping, not a logical stage.
    # human_gated investigations are parked awaiting operator decision —
    # not screened (which implies "decided no"), so they roll into
    # pending. Only explicit no_fix counts as screened.
    invest_with_pr = aged("investigate_done", lag_minutes=45,
                          pred=lambda e: e.get("produced_pr"))
    invest_no_fix = count("investigate_done",
                          pred=lambda e: e.get("no_fix"))
    invest_human_gated = count("investigate_done",
                               pred=lambda e: e.get("human_gated"))
    qa_done = count("qa_converged")
    qa_pending = _inbox_pending("qa") + invest_human_gated

    # qa → respond: PRs that qa passed should hit respond for a push.
    # screened = qa failures (verdict != pass).
    qa_pass = aged("qa_converged", lag_minutes=30,
                   pred=lambda e: e.get("verdict") == "pass")
    qa_fail = count("qa_converged",
                    pred=lambda e: e.get("verdict") != "pass")
    respond_done = count("respond_done")
    respond_pending = _inbox_pending("respond")

    # respond → ship: pushed responses should result in a PR pr-state can see.
    # Distinct (repo, pr) pairs in pr_state_classified within the
    # window is the closest proxy we have for "actually shipped".
    respond_pushed = aged("respond_done", lag_minutes=30,
                          pred=lambda e: e.get("pushed"))
    shipped_keys = {(e.get("repo"), e.get("pr")) for e in events
                    if e.get("kind") == "pr_state_classified"}
    shipped = len(shipped_keys)
    respond_not_pushed = count("respond_done",
                               pred=lambda e: not e.get("pushed"))

    # side-hatch: investigate → tissue → wipe → post.
    # Three hops, each with its own event balance:
    #   - tissue: drafts (LLM-shaped, can skip via policy or skill SKIP)
    #   - wipe:   approved drafts get posted (gh-shaped, can fail at API)
    #   - post:   the comment lands on the issue (engagement detector
    #             tracks reaction inside the 7-day window via tissue_engaged
    #             / tissue_muted, fed by leakdog tick)
    tissue_cards = aged("tissue_card_deposited", lag_minutes=30)
    tissue_drafted = count("tissue_drafted")
    tissue_skipped = count("tissue_skipped")
    tissue_pending = _inbox_pending("tissue")
    # tissue → wipe: operator approval is the queue between them.
    tissue_approved = count("tissue_approved")
    tissue_discarded = count("tissue_discarded")
    tissue_drafts_pending = _inbox_pending("tissue-drafts")
    # wipe → post: posts that landed vs failed.
    wipe_posted = count("tissue_posted")
    wipe_failed = count("tissue_post_failed")
    wipe_pending = _inbox_pending("wipe")

    # immunize: anti-AI escape hatch. Cards from sift (repo-level)
    # and triage (issue-level). Pursue → seed-or-draft; skip → silent
    # drop (policy resettled, below stars, archived, already seeded).
    immunize_cards = aged("immunize_card_deposited", lag_minutes=30)
    immunize_pursued = count("immunize_redirected")
    immunize_skipped = count("immunize_skipped")
    immunize_pending = _inbox_pending("immunize")

    # bless: classifier-router for tissue replies. Cards from leakdog
    # engagement detector. Three outputs: template (auto-draft from
    # catalog), auto (LLM draft, currently off), human (respondable
    # queue). "Screened" here = bless_skipped (no_fence, timeouts).
    bless_cards = aged("bless_card_deposited", lag_minutes=30)
    bless_routed = count("bless_routed")
    bless_skipped = count("bless_skipped")
    bless_pending = _inbox_pending("bless")

    # rows: (label, in, out, screened, pending)
    rows = [
        ("sift        → triage",      deposits,        triaged_total,  0,                triaged_pending),
        ("triage      → investigate", triaged_invest,  invest_done,    triaged_other,    invest_pending),
        ("(prosp|tri) → immunize",    immunize_cards,  immunize_pursued, immunize_skipped, immunize_pending),
        ("investigate → qa",          invest_with_pr,  qa_done,        invest_no_fix,    qa_pending),
        ("investigate → tissue",      tissue_cards,    tissue_drafted, tissue_skipped,   tissue_pending),
        ("engagement  → bless",       bless_cards,     bless_routed,   bless_skipped,    bless_pending),
        ("tissue      → wipe",        tissue_drafted,  tissue_approved, tissue_discarded, tissue_drafts_pending),
        ("wipe        → post",        tissue_approved, wipe_posted,    wipe_failed,      wipe_pending),
        ("qa          → respond",     qa_pass,         respond_done,   qa_fail,          respond_pending),
        ("respond     → ship",        respond_pushed,  shipped,        respond_not_pushed, 0),
    ]

    lines = [
        f"# Leakdog — sniffing, last {hours}h (target: 0)",
        "",
        "| interface | in | out | screened | pending | leak |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    total_leak = 0
    for label, inn, out, drop, pend in rows:
        leak = max(0, inn - out - drop - pend)
        total_leak += leak
        flag = " ⚠️" if leak > 0 else " ✅"
        lines.append(
            f"| {label} | {inn} | {out} | {drop} | {pend} | {leak}{flag} |"
        )
    lines += ["", f"_total leak: {total_leak} (zero is the target — "
              "`pending` items are in transit, not lost; `screened` "
              "items were filtered out by an explicit decision event "
              "and didn't continue here for a reason)._"]
    # Rejected jobs — skills that declined the work explicitly. Different
    # from `leak` (silent loss) and `screened` (decided-no). Rejection
    # means "I cannot fulfill this," and the operator should look.
    rejected = _rejected_summary(hours)
    if rejected:
        lines += ["", "**Rejected jobs (operator review):**", ""]
        for skill, n in rejected:
            lines.append(f"- `{skill}` × {n}")

    # Shim compliance — what fraction of skill outputs landed clean
    # vs needed Sonnet normalization vs fell through to heuristics.
    # The shim absorbs non-compliance; this row exposes it so the
    # producer pressure isn't invisible (the TDD-vs-shim trade).
    compliance = _shim_compliance()
    if compliance:
        lines += ["", "**Shim compliance (skill JSON output):**", ""]
        for row in compliance:
            lines.append(row)
    return lines


def _shim_compliance() -> list[str]:
    """Read shim_clean_fast / shim_normalized / shim_fallback counters
    by skill, format as `skill clean% normalized% fallback% (N total)`
    rows. Returns [] when no shim activity yet."""
    from sweep import observe
    counters = observe.counters_all()
    by_skill: dict[str, dict[str, int]] = {}
    for k, v in counters.items():
        for prefix, bucket in (
            ("shim_clean_fast:", "clean"),
            ("shim_normalized:", "normalized"),
            ("shim_fallback:",   "fallback"),
        ):
            if k.startswith(prefix):
                skill = k[len(prefix):]
                by_skill.setdefault(skill, {"clean": 0, "normalized": 0, "fallback": 0})
                by_skill[skill][bucket] = v
                break
    rows: list[str] = []
    for skill in sorted(by_skill):
        d = by_skill[skill]
        total = d["clean"] + d["normalized"] + d["fallback"]
        if not total:
            continue
        pct = lambda x: f"{100 * x // total:3d}%"
        rows.append(
            f"- `{skill}` — clean {pct(d['clean'])} · "
            f"normalized {pct(d['normalized'])} · "
            f"fallback {pct(d['fallback'])} (n={total})"
        )
    return rows


def _rejected_summary(hours: int) -> list[tuple[str, int]]:
    """Count rejected-inbox entries by skill in the last `hours`. Returns
    [(skill, count), ...] sorted by count desc, or [] when none."""
    import datetime as _dt
    import json as _json
    from collections import Counter
    from pathlib import Path
    path = Path.home() / ".sweep" / "inbox" / "rejected.jsonl"
    if not path.exists():
        return []
    cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=hours)
    counts: Counter[str] = Counter()
    try:
        text = path.read_text()
    except OSError:
        return []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            entry = _json.loads(line)
        except _json.JSONDecodeError:
            continue
        try:
            ts = _dt.datetime.fromisoformat(entry.get("ts", ""))
        except (ValueError, TypeError):
            continue
        if ts < cutoff:
            continue
        counts[entry.get("skill", "unknown")] += 1
    return counts.most_common()


# ---------------------------------------------------------- entry


def lanes(
    height: int = typer.Option(7, "--height", help="Max rows per column before truncating"),
    as_json: bool = typer.Option(False, "--json", help="Emit structured data for the TUI overlay"),
) -> None:
    """Column view: which PR is in which station. No numerics, truncates tall columns.

    With ``--json``, emits a list of columns ``[{label, items: [{repo, pr, in_flight}]}]``
    for the lanes TUI overlay to consume (`sweep tui` → `l`).
    """
    if as_json:
        import json as _json
        cols = []
        for actor, label in STATIONS:
            s = inbox_states(actor)
            in_flight_ids = {m.get("msg_id") for m in s["in_flight"]}
            msgs = sorted(s["queued"] + s["in_flight"], key=lambda x: x.get("ts", ""))
            items = [{
                "repo": m.get("repo", "?"),
                "pr": m.get("pr") or "-",
                "in_flight": m.get("msg_id") in in_flight_ids,
            } for m in msgs]
            cols.append({"label": label, "items": items})
        print(_json.dumps(cols))
        return
    print("# Sweep lanes")
    print()
    for line in render_lanes(height):
        print(line)
    # Provenance — for each active item, the chain of where it's been.
    # Faithfully records the sequence; interpretations (backflow count,
    # cycle-time distributions, station dwell, etc.) read FROM this
    # rather than being baked in. Separation of recording from analysis
    # is the same discipline as events.jsonl itself.
    for line in _render_provenance_section():
        print(line)
    # Leakdog sits adjacent to lanes: lanes is point-in-time inventory,
    # leakdog is the flow accounting across station interfaces over the
    # recent window. Together they tell you both "where is each PR" and
    # "where did the missing ones go."
    print()
    for line in render_leakdog():
        print(line)
