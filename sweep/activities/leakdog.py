"""leakdog activities — periodic sniffing for two kinds of leak.

This module owns the *daemon-side* of leakdog. The view-side
(`render_leakdog`) lives in `sweep.cli.lanes` next to the swim-lane
table where it surfaces interface leaks at a glance.

The activity here is what makes leakdog *independent* of any one
workflow's health: it runs on its own tick (driven by the
`LeakdogDaemon` workflow) so a wedged prospect-puller can't trap the
API-budget andon in the "set" state. That was [[H21]] — the supervisor
must not be supervised by the thing it supervises.
"""

from __future__ import annotations

from temporalio import activity


@activity.defn
async def leakdog_tick() -> dict:
    """One leakdog pass. Two responsibilities:
      1. Resource-leak watchdog (API budget auto-clear).
      2. Inbox-staleness refresh — re-check items whose precondition
         may have become false since delivery (e.g. respondable items
         where we already responded), and ack the ones that have.

    Intentionally never raises — leakdog itself andoning would be
    ironic and would block its own recovery."""
    out: dict = {}
    # --- (1) API budget watchdog ----------------------------------
    try:
        from sweep.activities.prospect import (
            _api_budget_block, _clear_budget_andon_if_held,
        )
        from sweep.activities import prospect as _prospect
        _prospect._api_budget_cache["ts"] = 0.0
        reason = _api_budget_block()
        out["budget_block_reason"] = reason
        cleared = _clear_budget_andon_if_held() if reason is None else False
        out["budget_andon_cleared_directly"] = cleared
    except Exception as e:
        out["budget_error"] = f"{type(e).__name__}: {str(e)[:200]}"

    # --- (2) Per-actor budget watchdog ----------------------------
    # Higher-resolution than the global core-budget check above: each
    # actor declares its own share, accumulates calls in its own log,
    # and pulls its own andon when it exceeds (share + overshoot).
    # Leakdog auto-clears the per-actor andon when usage drops back
    # under the actor's share (no extra hysteresis needed — the share
    # boundary is itself the dead band before re-firing at +overshoot).
    try:
        from sweep import budget as _budget
        per_actor = {}
        for actor in _budget.SHARES:
            reason = _budget.check_and_andon(actor)
            if reason:
                per_actor[actor] = reason
            else:
                # Under cap — try to clear any held andon for this actor.
                if _budget.clear_andon_if_held(actor):
                    per_actor[actor] = "cleared"
        out["per_actor_budget"] = per_actor
    except Exception as e:
        out["per_actor_budget_error"] = f"{type(e).__name__}: {str(e)[:200]}"

    # --- (3) Respondable inbox staleness refresh ------------------
    # When the operator answers a maintainer's question on GitHub,
    # the PR's bucket flips away from "respondable" but our inbox
    # entry lingers until either the maintainer replies (notification
    # poller catches it) or the full pr-state rescan runs. Leakdog
    # closes that gap: re-fetch the PR (5min TTL cache, so this
    # batches cheaply across ticks) and ack inbox entries whose
    # precondition no longer holds.
    try:
        refreshed = await _refresh_respondable_inbox()
        out["respondable_refreshed"] = refreshed
    except Exception as e:
        out["respondable_error"] = f"{type(e).__name__}: {str(e)[:200]}"

    return out


async def _refresh_respondable_inbox() -> dict:
    """For each unique (repo, pr) in the respondable inbox's queued
    set, re-fetch the PR state and ack the msg if the bucket has
    moved away from 'respondable'. Returns counts for the tick log."""
    import json
    from pathlib import Path
    from sweep import gh_io
    from sweep.activities.pr_state import classify_one_pr
    from sweep.types import PrLiveState

    inbox_path = Path.home() / ".sweep" / "inbox" / "respondable.jsonl"
    acks_path = Path.home() / ".sweep" / "inbox" / "_acks.jsonl"
    if not inbox_path.exists():
        return {"checked": 0, "acked": 0}

    # Existing acks — don't double-ack.
    acked: set[str] = set()
    if acks_path.exists():
        for line in acks_path.read_text().splitlines():
            if not line.strip(): continue
            try: acked.add(json.loads(line).get("msg_id"))
            except Exception: pass

    # Queued = inbox msg whose msg_id is not in acks. Dedupe by (repo, pr)
    # so a re-delivered PR only burns one gh call.
    by_pr: dict[tuple, list[str]] = {}
    for line in inbox_path.read_text().splitlines():
        if not line.strip(): continue
        try:
            m = json.loads(line)
        except Exception:
            continue
        if m.get("msg_id") in acked:
            continue
        repo, pr = m.get("repo"), m.get("pr")
        if not repo or not pr:
            continue
        by_pr.setdefault((repo, pr), []).append(m.get("msg_id"))

    if not by_pr:
        return {"checked": 0, "acked": 0}

    import datetime as _dt
    now_iso = _dt.datetime.now(_dt.timezone.utc).isoformat()
    new_acks: list[str] = []
    for (repo, pr), msg_ids in by_pr.items():
        try:
            # 5-min TTL so successive leakdog ticks share the cache.
            data = gh_io.pr_view(repo, pr, ttl=300)
        except Exception:
            continue
        if not data:
            continue
        # Build a PrLiveState; classify_one_pr expects this shape.
        # Mirrors the field extraction in activities.pr_state.gh_pr_view.
        live = _live_state_from_gh(repo, pr, data)
        if live is None:
            continue
        try:
            result = await classify_one_pr(live)
        except Exception:
            continue
        if result.bucket == "respondable":
            continue  # still respondable; leave it
        # Bucket changed — ack every msg referring to this PR.
        for mid in msg_ids:
            new_acks.append(json.dumps({
                "msg_id": mid, "ts": now_iso, "from": "leakdog",
                "outcome": f"bucket-changed-to-{result.bucket}",
            }))
    if new_acks:
        acks_path.parent.mkdir(parents=True, exist_ok=True)
        with open(acks_path, "a") as f:
            f.write("\n".join(new_acks) + "\n")
    return {"checked": len(by_pr), "acked": len(new_acks)}


def _live_state_from_gh(repo: str, pr: int, data: dict):
    """Re-derive a PrLiveState from the cached gh pr_view payload.

    Subset of the logic in activities.pr_state.gh_pr_view — we only
    need the fields classify_one_pr touches. Reimplemented here to
    avoid pulling in the activity decorator (which would be a no-op
    here) and to keep leakdog's dependencies narrow.
    """
    import datetime as _dt
    from sweep.types import PrLiveState
    try:
        updated_at = data.get("updatedAt", "")
        if updated_at:
            t = _dt.datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            activity_h = (_dt.datetime.now(_dt.timezone.utc) - t).total_seconds() / 3600
        else:
            activity_h = 0.0
    except Exception:
        activity_h = 0.0
    # ci roll-up — green if all checks pass; failing if any failure;
    # pending if there are running checks; otherwise unknown. Same
    # spirit as gh_pr_view but minimal.
    rollup = data.get("statusCheckRollup") or []
    ci = "unknown"
    failing_check = ""
    if rollup:
        states = [c.get("state") or c.get("conclusion") or "" for c in rollup]
        if any(s in ("FAILURE", "ERROR", "TIMED_OUT", "CANCELLED") for s in states):
            ci = "failing"
            for c in rollup:
                s = c.get("state") or c.get("conclusion") or ""
                if s in ("FAILURE", "ERROR", "TIMED_OUT", "CANCELLED"):
                    failing_check = c.get("name", "") or c.get("context", "")
                    break
        elif any(s in ("IN_PROGRESS", "PENDING", "QUEUED") for s in states):
            ci = "pending"
        elif all(s in ("SUCCESS", "NEUTRAL", "SKIPPED", "") for s in states):
            ci = "green"
    return PrLiveState(
        repo=repo, pr=pr,
        branch=data.get("headRefName", ""),
        title=data.get("title", ""),
        url=data.get("url", ""),
        review_decision=data.get("reviewDecision", "") or "",
        mergeable=data.get("mergeable", "") or "",
        ci=ci,
        activity_h=activity_h,
        maintainer_question=False,  # conservative; classify_one_pr handles
        is_draft=bool(data.get("isDraft", False)),
        failing_check=failing_check,
    )
