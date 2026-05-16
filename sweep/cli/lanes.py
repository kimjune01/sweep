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
    ("drip",        "drip"),
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
      prospect    → triage       (deposit → triage_decision)
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

    # prospect → triage: every deposit should trigger a triage_decision
    deposits = aged("prospect_deposited", lag_minutes=15)
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
    invest_with_pr = aged("investigate_done", lag_minutes=45,
                          pred=lambda e: e.get("produced_pr"))
    invest_no_fix = count("investigate_done",
                          pred=lambda e: e.get("no_fix") or not e.get("produced_pr"))
    qa_done = count("qa_converged")
    qa_pending = _inbox_pending("qa")

    # qa → drip: PRs that qa passed should hit drip for a push.
    # screened = qa failures (verdict != pass).
    qa_pass = aged("qa_converged", lag_minutes=30,
                   pred=lambda e: e.get("verdict") == "pass")
    qa_fail = count("qa_converged",
                    pred=lambda e: e.get("verdict") != "pass")
    drip_done = count("drip_done")
    drip_pending = _inbox_pending("drip")

    # drip → ship: pushed drips should result in a PR pr-state can see.
    # Distinct (repo, pr) pairs in pr_state_classified within the
    # window is the closest proxy we have for "actually shipped".
    drip_pushed = aged("drip_done", lag_minutes=30,
                       pred=lambda e: e.get("pushed"))
    shipped_keys = {(e.get("repo"), e.get("pr")) for e in events
                    if e.get("kind") == "pr_state_classified"}
    shipped = len(shipped_keys)
    drip_not_pushed = count("drip_done",
                            pred=lambda e: not e.get("pushed"))

    # rows: (label, in, out, screened, pending)
    rows = [
        ("prospect    → triage",      deposits,        triaged_total,  0,               triaged_pending),
        ("triage      → investigate", triaged_invest,  invest_done,    triaged_other,   invest_pending),
        ("investigate → qa",          invest_with_pr,  qa_done,        invest_no_fix,   qa_pending),
        ("qa          → drip",        qa_pass,         drip_done,      qa_fail,         drip_pending),
        ("drip        → ship",        drip_pushed,     shipped,        drip_not_pushed, 0),
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
    # Leakdog sits adjacent to lanes: lanes is point-in-time inventory,
    # leakdog is the flow accounting across station interfaces over the
    # recent window. Together they tell you both "where is each PR" and
    # "where did the missing ones go."
    print()
    for line in render_leakdog():
        print(line)
