"""Metronome — cadence schedule + tick activity.

Schedule lives in code so it ships with the worker; if a target needs
runtime tuning, externalize per-target to a ~/.sweep/control/<name>
file the same way rope's target works. Don't grow this dict into a
config format until two targets actually need different overrides.

Each tick reads ~/.sweep/metronome/last_fired.json for per-target
last-fired timestamps (durable across restart), kicks every target
that's due, and returns the seconds until the next-due entry so the
MetronomeActor can sleep that long.
"""

from __future__ import annotations

import datetime as dt
import json
from datetime import timedelta
from pathlib import Path

from temporalio import activity

from sweep.types import Message, forward_ledger


STATE_FILE = Path.home() / ".sweep" / "metronome" / "last_fired.json"


# (target_actor, cadence) — extensible. retro is first; future
# cadence-driven kicks land here without new workflow code.
SCHEDULE: list[tuple[str, timedelta]] = [
    ("retro", timedelta(hours=24)),
    ("heart", timedelta(minutes=15)),
    ("usage", timedelta(minutes=5)),
    # evict — drain sink.jsonl entries (draft+apology for unattestable,
    # self-close for test_passes_on_master / other authoritative). Same
    # cadence as usage so the post_disabled latch is honored uniformly.
    ("evict", timedelta(minutes=10)),
    # ping — 5-min wakeup to drain queued drafts. Outbound timing
    # matters at hour-scale (don't ping a maintainer at 2am their TZ),
    # but the eligibility logic gates that internally; the metronome's
    # job is just to ensure the actor pulls its queue. Witnessed parked
    # 24h on the old hourly cadence — drafts sat because the actor was
    # never woken to even check.
    ("ping", timedelta(minutes=5)),
    # broom — daily 5S sweep of ~/.sweep/ files. Drops acked inbox
    # messages, dangling ack/started tombstones, age-old events / sink /
    # budget entries, rotates oversized logs. Per-file policies live in
    # sweep/broom.py; tunables under ~/.sweep/control/retain/<name>.
    ("broom", timedelta(hours=24)),
    # reinvestigate — nudge the actor every 5 min to pull its queue.
    # Engagement-lane cards land on reinvestigate.jsonl from remit;
    # without a wake-up signal (worker restart, missed Temporal signal),
    # queued work can sit despite WIP-cap headroom. This is a cheap
    # "check your inbox" tick, not a card-deposit — uses the signal
    # channel directly so it doesn't bloat the queue.
    ("reinvestigate", timedelta(minutes=5)),
    # sign — same shape: nudge sign-actor to pull queued CLA/DCO cards.
    # Cards land from remit (failing CLA-class check classification) and
    # may also arrive via manual backfill. Cycle is cheap (gh fetch +
    # sonnet shim + at most two gh comment posts) so 5-min cadence is
    # generous.
    ("sign", timedelta(minutes=5)),
    # roll — search cadence. Rope is the demand-side tug (fires when
    # roll's queue is idle); metronome is the supply-side wake-up that
    # guarantees roll keeps probing even when no downstream demand
    # signal arrives (cold start, paused-then-resumed line, etc.).
    # 10-min cadence pairs with the budget self-throttle: roll's share
    # caps actual fires regardless of how often metronome wakes it.
    ("roll", timedelta(minutes=10)),
]


def _load_state() -> dict[str, str]:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(state: dict[str, str]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True))


async def _kick(target: str) -> None:
    """Dispatch to the target's kick_*_card helper. Per-target because
    each kicker has different required args (repo, sender, etc.); the
    metronome only knows about cadence, not target semantics."""
    from sweep import observe
    if target == "retro":
        from sweep.activities.retro import kick_retro_card
        await kick_retro_card(sender="metronome")
    elif target == "heart":
        from sweep.activities.heart import kick_heart_card
        await kick_heart_card(sender="metronome")
    elif target == "usage":
        # No inbox/actor for usage — it's a stateless probe. Call the
        # activity body directly; the call records claude-quota events
        # the wasteboard and cockpit read. Replaces the separate
        # UsagePoller workflow.
        from sweep.activities.usage_probe import probe_claude_usage
        try:
            await probe_claude_usage()
        except Exception as e:
            observe.event("metronome_usage_probe_failed",
                          error_type=type(e).__name__, error=str(e)[:200])
    elif target == "evict":
        # Drain sink: draft+apology or self-close per reason. Honors
        # post_disabled (the CLI's own gh calls do the post; if the
        # operator has the flag set, those drafts/closes don't fire,
        # but the metronome safely re-tries every 10min).
        try:
            from sweep.cli.evict import _read_sink, _apology_for, \
                _should_self_close, _is_do_not_evict, \
                _gh_pr_state, _close_with_comment, _draft_and_comment
            from pathlib import Path as _P
            if (_P.home() / ".sweep" / "control" / "post_disabled").exists():
                observe.event("metronome_evict_skipped_post_disabled")
                return
            rows = _read_sink()
            latest: dict[tuple[str, int], dict] = {}
            for r in rows:
                if r.get("repo") and r.get("pr"):
                    latest[(r["repo"], int(r["pr"]))] = r
            drafted = closed = skipped = failed = 0
            for (repo, pr), r in sorted(latest.items()):
                reason = r.get("reason", "?")
                if _is_do_not_evict(reason):
                    skipped += 1
                    continue
                state = _gh_pr_state(repo, pr)
                if state is None or state.get("state") != "OPEN":
                    skipped += 1
                    continue
                if state.get("reviewDecision") == "APPROVED":
                    skipped += 1
                    continue
                comment = _apology_for(reason)
                if _should_self_close(reason):
                    ok, _ = _close_with_comment(repo, pr, comment)
                    closed += 1 if ok else 0
                    failed += 0 if ok else 1
                else:
                    if state.get("isDraft"):
                        skipped += 1
                        continue
                    ok, _ = _draft_and_comment(repo, pr, comment)
                    drafted += 1 if ok else 0
                    failed += 0 if ok else 1
            observe.event("metronome_evict_cycle",
                          drafted=drafted, closed=closed,
                          skipped=skipped, failed=failed)
        except Exception as e:
            observe.event("metronome_evict_failed",
                          error_type=type(e).__name__, error=str(e)[:200])
    elif target == "sign":
        try:
            import datetime as _dt
            from sweep.types import Message
            from sweep.activities.pr_state import _signal_actor
            ts = _dt.datetime.now(_dt.timezone.utc)
            nudge = Message(
                msg_id=f"sign-nudge-{ts.strftime('%Y%m%dT%H%M%S')}",
                sender="metronome", intent="nudge",
                repo="", pr=None, branch=None,
                payload={}, ts=ts.isoformat(),
            )
            wf = await _signal_actor("sign", nudge)
            observe.event("metronome_sign_nudge", wf=wf or "(no-wf)")
        except Exception as e:
            observe.event("metronome_sign_nudge_failed",
                          error_type=type(e).__name__, error=str(e)[:200])
    elif target == "reinvestigate":
        # Wake-up signal only — no inbox write. The actor's own loop
        # decides what to pull based on WIP cap + queue depth.
        try:
            import datetime as _dt
            from sweep.types import Message
            from sweep.activities.pr_state import _signal_actor
            ts = _dt.datetime.now(_dt.timezone.utc)
            nudge = Message(
                msg_id=f"reinvestigate-nudge-{ts.strftime('%Y%m%dT%H%M%S')}",
                sender="metronome", intent="nudge",
                repo="", pr=None, branch=None,
                payload={}, ts=ts.isoformat(),
            )
            wf = await _signal_actor("reinvestigate", nudge)
            observe.event("metronome_reinvestigate_nudge", wf=wf or "(no-wf)")
        except Exception as e:
            observe.event("metronome_reinvestigate_nudge_failed",
                          error_type=type(e).__name__, error=str(e)[:200])
    elif target == "broom":
        # 5S sweep — drop acked inbox, dangling tombstones, aged
        # events/sink/budget, rotate logs. Stays in-process (no
        # actor/inbox); the broom module is pure file I/O.
        try:
            from sweep import broom as _broom
            results = _broom.sweep_all(dry_run=False)
            summary = _broom.summary(results)
            observe.event("metronome_broom_cycle", **summary)
        except Exception as e:
            observe.event("metronome_broom_failed",
                          error_type=type(e).__name__, error=str(e)[:200])
    elif target == "ping":
        # Hourly eligibility re-check: walk ping.jsonl, for each draft
        # whose scheduled_for has passed AND that hasn't already been
        # drafted (per ping_drafted ledger), run the deterministic
        # precondition (attestation manifest + gh CI + post_disabled)
        # and draft to human inbox. Honors post_disabled — if set,
        # noop the whole scan, drafts stay parked until the latch
        # clears AND their scheduled_for is past.
        try:
            from sweep.activities.ping import (
                _scan_due_drafts_and_emit,
            )
            result = await _scan_due_drafts_and_emit()
            observe.event("metronome_ping_scan",
                          checked=result.get("checked", 0),
                          drafted=result.get("drafted", 0),
                          skipped_not_due=result.get("skipped_not_due", 0),
                          skipped_already_drafted=result.get("skipped_already_drafted", 0))
        except Exception as e:
            observe.event("metronome_ping_failed",
                          error_type=type(e).__name__, error=str(e)[:200])
    elif target == "roll":
        from sweep.activities.roll import kick_roll_card
        await kick_roll_card(sender="metronome")
    else:
        observe.event("metronome_unknown_target", target=target)


@activity.defn
async def metronome_tick(manual: Message | None = None) -> dict:
    """Fire every due target; return seconds until next-due so the
    workflow can sleep that long.

    `manual`: present when an operator deposited a card on the
    metronome's inbox to force evaluation. Doesn't change due-logic;
    just lets the actor record who asked.
    """
    from sweep import observe

    state = _load_state()
    now = dt.datetime.now(dt.timezone.utc)
    fired: list[str] = []
    earliest_next: float | None = None

    # Jitter: each cadence gets multiplied by uniform(0.9, 1.1) per
    # tick so independent metronome targets don't fire in lockstep.
    # Without this, every 5-min target (heart/usage/evict/reinvestigate/
    # sign/broom-ish) syncs to the same modulo-300s phase and produces
    # a thundering-herd burst every 5 min instead of paced firing.
    # Flat distribution (rather than gaussian) keeps the bound hard at
    # ±10%; no long-tail wait.
    import random as _random
    for target, cadence in SCHEDULE:
        last_iso = state.get(target)
        if last_iso:
            try:
                last = dt.datetime.fromisoformat(last_iso)
            except ValueError:
                last = None
        else:
            last = None

        jittered = cadence * _random.uniform(0.9, 1.1)
        next_due = (last + jittered) if last else now
        if next_due <= now:
            try:
                await _kick(target)
                state[target] = now.isoformat()
                fired.append(target)
                target_next = jittered.total_seconds()
            except Exception as e:
                observe.event(
                    "metronome_kick_failed", target=target,
                    error_type=type(e).__name__, error=str(e)[:200],
                )
                # Don't update last_fired on failure — retry next tick.
                target_next = 60.0
        else:
            target_next = (next_due - now).total_seconds()

        if earliest_next is None or target_next < earliest_next:
            earliest_next = target_next

    if fired:
        _save_state(state)

    observe.event(
        "metronome_tick",
        fired=fired,
        manual_msg_id=(manual.msg_id if manual else None),
        next_due_seconds=earliest_next,
    )
    return {
        "fired": fired,
        "next_due_seconds": earliest_next,
        "schedule_size": len(SCHEDULE),
    }


@activity.defn
async def kick_metronome_card(sender: str = "operator",
                              incoming: Message | None = None) -> str | None:
    """Operator or other-actor entry point: force a metronome evaluation
    pass right now (don't wait for the next scheduled wake)."""
    from sweep import observe
    from sweep.activities.pr_state import _signal_actor

    ts = dt.datetime.now(dt.timezone.utc)
    msg_id = f"metronome-{ts.strftime('%Y%m%dT%H%M%S')}-{sender}"
    msg = Message(
        msg_id=msg_id,
        sender=sender,
        intent="tick",
        ts=ts.isoformat(),
        ledger=forward_ledger(incoming),
    )
    INBOX = Path.home() / ".sweep" / "inbox" / "metronome.jsonl"
    INBOX.parent.mkdir(parents=True, exist_ok=True)
    from dataclasses import asdict
    try:
        with open(INBOX, "a") as f:
            f.write(json.dumps(asdict(msg)) + "\n")
    except Exception as e:
        observe.event("metronome_card_write_failed",
                      error_type=type(e).__name__, error=str(e)[:200])
        return None
    return await _signal_actor("metronome", msg)
