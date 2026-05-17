"""`sweep leakdog` — funnel-balance accounting across station interfaces.

Each row is "items entering interface = items continuing + items dropped
with a recorded reason." Anything missing is a LEAK. Target is zero;
every drop should be explained by an explicit decision event.

Lag tolerance: an item upstream that's younger than the interface's lag
isn't a leak; it's in flight. Without this, every fresh deposit looks
like a triage leak.
"""

from __future__ import annotations

import datetime as dt
import json
from collections import Counter
from pathlib import Path

import typer

from sweep.inbox_state import inbox_states


def register(app: typer.Typer) -> None:
    app.command("leakdog")(leakdog)


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
    """Items currently queued or in-flight at an actor's station — 'in
    transit, not leaked'. Subtract from raw leak counts so slow
    processing doesn't look like loss."""
    try:
        s = inbox_states(actor)
        return len(s.get("queued", [])) + len(s.get("in_flight", []))
    except Exception:
        return 0


# Actors where the substrate's invariant is "one msg_id per (repo, pr)".
# Routing-shaped actors fed from remit should satisfy this; the
# scout→sift fan-out emits one card per RAW ISSUE so per-card uniqueness
# is the expected shape there too. Drift here means a producer is
# minting fresh msg_ids for the same logical item, wasting writes and
# polluting downstream counts.
_DEDUP_ACTORS = ("triaged", "investigate", "qa", "respond", "human",
                 "retro", "tissue", "bless", "immunize", "post",
                 "submit", "remit")


def inbox_drift_summary() -> list[tuple[str, int, int]]:
    """For each dedup actor, return (name, distinct_msg_ids, distinct_repo_pr)
    tuples ONLY when the two diverge (drift > 0). Empty list = clean."""
    out: list[tuple[str, int, int]] = []
    for actor in _DEDUP_ACTORS:
        try:
            s = inbox_states(actor)
            msgs = s.get("queued", []) + s.get("in_flight", [])
            if not msgs:
                continue
            distinct_msgs = len({m.get("msg_id") for m in msgs if m.get("msg_id")})
            distinct_keys = len({(m.get("repo"), m.get("pr")) for m in msgs})
            if distinct_msgs != distinct_keys:
                out.append((actor, distinct_msgs, distinct_keys))
        except Exception:
            continue
    return out


def _compute_balances(hours: int) -> tuple[list[tuple], list[tuple]]:
    """Walk events once and return (spine_rows, hatch_rows). Each row is
    `(label, in, out, screened, pending)`. Shared by `render_leakdog`
    (full table) and `leak_summary` (cockpit chip)."""
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
    # through to a qa_converged outcome. remit is the dispatcher
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

    # respond → submit: pushed responses should result in a PR remit can see.
    # Distinct (repo, pr) pairs in remit_classified within the
    # window is the closest proxy we have for "actually submitted".
    respond_pushed = aged("respond_done", lag_minutes=30,
                          pred=lambda e: e.get("pushed"))
    submitted_keys = {(e.get("repo"), e.get("pr")) for e in events
                      if e.get("kind") in ("remit_classified", "pr_state_classified")}
    submitted = len(submitted_keys)
    respond_not_pushed = count("respond_done",
                               pred=lambda e: not e.get("pushed"))

    # side-hatch: investigate → tissue → approval → posted.
    # Three hops, each with its own event balance:
    #   - tissue:   drafts (LLM-shaped, can skip via policy or skill SKIP)
    #   - approval: drafts wait for operator approve/discard
    #   - posted:   post-actor posts approved drafts via gh (engagement
    #               detector tracks reaction inside the 7-day window via
    #               tissue_engaged / tissue_muted, fed by leakdog tick)
    tissue_cards = aged("tissue_card_deposited", lag_minutes=30)
    tissue_drafted = count("tissue_drafted")
    tissue_skipped = count("tissue_skipped")
    tissue_pending = _inbox_pending("tissue")
    # draft → approval: operator approval/discard is the queue between them.
    tissue_approved = count("tissue_approved")
    tissue_discarded = count("tissue_discarded")
    tissue_drafts_pending = _inbox_pending("tissue-drafts")
    # approval → posted: post-actor posts approved drafts; tracks landed vs failed.
    posts_landed = count("tissue_posted")
    posts_failed = count("tissue_post_failed")
    posts_pending = _inbox_pending("post")

    # immunize: anti-AI escape hatch. Cards from sift (repo-level)
    # and triage (issue-level). Pursue → seed-or-draft; skip → silent
    # drop (policy resettled, below stars, archived, already seeded).
    immunize_cards = aged("immunize_card_deposited", lag_minutes=30)
    immunize_pursued = count("immunize_redirected")
    immunize_skipped = count("immunize_skipped")
    immunize_pending = _inbox_pending("immunize")

    # bless: classifier-router for tissue replies. Cards from leakdog
    # engagement detector. Three outputs: template (auto-draft from
    # catalog), auto (LLM draft, currently off), human (human-issues
    # queue). "Screened" here = bless_skipped (no_fence, timeouts).
    bless_cards = aged("bless_card_deposited", lag_minutes=30)
    bless_routed = count("bless_routed")
    bless_skipped = count("bless_skipped")
    bless_pending = _inbox_pending("bless")

    spine = [
        ("sift        → triage",      deposits,        triaged_total,  0,                  triaged_pending),
        ("triage      → investigate", triaged_invest,  invest_done,    triaged_other,      invest_pending),
        ("investigate → qa",          invest_with_pr,  qa_done,        invest_no_fix,      qa_pending),
        ("qa          → respond",     qa_pass,         respond_done,   qa_fail,            respond_pending),
        ("respond     → submit",      respond_pushed,  submitted,      respond_not_pushed, 0),
    ]
    hatches = [
        ("immunize", immunize_cards,  immunize_pursued, immunize_skipped, immunize_pending),
        ("tissue",   tissue_cards,    tissue_drafted,   tissue_skipped,   tissue_pending),
        ("bless",    bless_cards,     bless_routed,     bless_skipped,    bless_pending),
        ("draft → approval",   tissue_drafted,  tissue_approved, tissue_discarded, tissue_drafts_pending),
        ("approval → posted",  tissue_approved, posts_landed,    posts_failed,     posts_pending),
    ]
    return spine, hatches


def _leak_of(inn: int, out: int, drop: int, pend: int) -> int:
    return max(0, inn - out - drop - pend)


def leak_summary(hours: int = 24) -> list[tuple[str, int]]:
    """Compact attention list: `[(label, leak_count), ...]` for non-zero
    rows only. Empty list means clean. Cockpit uses this to render a
    silent-when-ok chip; full breakdown stays in `sweep leakdog`."""
    spine, hatches = _compute_balances(hours)
    out: list[tuple[str, int]] = []
    for label, inn, o, drop, pend in spine:
        leak = _leak_of(inn, o, drop, pend)
        if leak > 0:
            out.append((label.strip(), leak))
    for name, inn, o, drop, pend in hatches:
        leak = _leak_of(inn, o, drop, pend)
        if leak > 0:
            out.append((name, leak))
    return out


def render_leakdog(hours: int = 24) -> list[str]:
    """Funnel-balance table over the last `hours`. Returns markdown lines.

    Interfaces:
      sift        → triage       (deposit → triage_decision)
      triage      → investigate  (triage_decision=investigate → investigate_done)
      investigate → drip         (investigate_done(produced_pr) → remit_classified)
      remit       → qa           (remit_classified(bucket=qa) → qa_converged)

    A row's `leak` = `in − (out + screened + still_in_inbox)`. The inbox
    subtraction is what separates real loss from slow processing. Lag
    tolerance still applies to `in` so items too fresh to have been
    processed yet don't get counted."""
    spine, hatches = _compute_balances(hours)
    leak_of = _leak_of

    lines = [
        f"# Leakdog — sniffing, last {hours}h (target: 0)",
        "",
        "| interface | in | out | screened | pending | leak |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    total_leak = 0
    for label, inn, out, drop, pend in spine:
        leak = leak_of(inn, out, drop, pend)
        total_leak += leak
        flag = " ⚠️" if leak > 0 else " ✅"
        lines.append(f"| {label} | {inn} | {out} | {drop} | {pend} | {leak}{flag} |")

    # Side-hatches: expand only the leaking ones; summarize the rest.
    leaking_hatches = [(n, i, o, d, p, leak_of(i, o, d, p)) for n, i, o, d, p in hatches
                       if leak_of(i, o, d, p) > 0]
    for name, inn, out, drop, pend, leak in leaking_hatches:
        total_leak += leak
        lines.append(f"| _hatch:_ `{name}` | {inn} | {out} | {drop} | {pend} | {leak} ⚠️ |")
    clean_hatches = [n for n, i, o, d, p in hatches if leak_of(i, o, d, p) == 0]
    if clean_hatches:
        lines.append(f"| _side-hatches ok_ | | | | | {', '.join(clean_hatches)} ✅ |")

    lines += ["", f"_total leak: {total_leak}._"]

    # Inbox-drift detector: when distinct msg_ids and distinct (repo, pr)
    # diverge in an actor's queued+in-flight set, a producer is minting
    # fresh ids for the same logical item. Surfaces the same condition
    # the lanes render-layer used to silently `set()`-dedup.
    drift = inbox_drift_summary()
    if drift:
        lines += ["", "**Inbox drift (msg_ids ≠ distinct (repo, pr)):**", ""]
        for actor, n_msgs, n_keys in drift:
            lines.append(f"- `{actor}` — {n_msgs} msg_ids / {n_keys} distinct PRs "
                         f"(drift: {n_msgs - n_keys})")
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
    path = Path.home() / ".sweep" / "inbox" / "rejected.jsonl"
    if not path.exists():
        return []
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
    counts: Counter[str] = Counter()
    try:
        text = path.read_text()
    except OSError:
        return []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            ts = dt.datetime.fromisoformat(entry.get("ts", ""))
        except (ValueError, TypeError):
            continue
        if ts < cutoff:
            continue
        counts[entry.get("skill", "unknown")] += 1
    return counts.most_common()


def leakdog(
    hours: int = typer.Option(24, "--hours", "-h", help="Lookback window in hours"),
) -> None:
    """Flow accounting across station interfaces. Each row balances
    items in vs out + screened + pending; anything else is a leak."""
    for line in render_leakdog(hours):
        print(line)
