"""leakdog activities — periodic sniffing for two kinds of leak.

This module owns the *daemon-side* of leakdog. The view-side
(`render_leakdog`) lives in `sweep.cli.leakdog` as its own command.

The activity here is what makes leakdog *independent* of any one
workflow's health: it runs on its own tick (driven by the
`LeakdogDaemon` workflow) so a wedged actor can't trap the
API-budget andon in the "set" state. That was [[O2]] — the supervisor
must not be supervised by the thing it supervises.
"""

from __future__ import annotations

from temporalio import activity


@activity.defn
async def leakdog_tick() -> dict:
    """One leakdog pass. Two responsibilities:
      1. Resource-leak watchdog (API budget auto-clear).
      2. Inbox-staleness refresh — re-check items whose precondition
         may have become false since delivery (e.g. human-bucket items
         where we already responded), and ack the ones that have.

    Intentionally never raises — leakdog itself andoning would be
    ironic and would block its own recovery."""
    out: dict = {}
    # --- (1) API budget watchdog ----------------------------------
    try:
        from sweep import api_budget
        # Force the cache to refresh: leakdog's job is to be more
        # current than the puller's cached read.
        api_budget._api_budget_cache["ts"] = 0.0
        reason = api_budget._api_budget_block()
        out["budget_block_reason"] = reason
        cleared = (api_budget._clear_budget_andon_if_held()
                   if reason is None else False)
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

    # --- Comment-issue engagement detector ------------------------------
    # For each posted comment-issue inside its 7-day window, poll the issue
    # for any activity since post_ts (reply, reaction, close, label,
    # mention). Emit `tissue_engaged` on first hit; emit `tissue_muted`
    # when the window closes silent. Both events feed the H23 verdict.
    try:
        out["tissue_engagement"] = await _tissue_engagement_sweep()
    except Exception as e:
        out["tissue_engagement_error"] = f"{type(e).__name__}: {str(e)[:200]}"

    # --- (3) Scout pull-signal heartbeat --------------------------
    # Pull source of truth is triage's ack path (each ack emits one
    # card). This heartbeat is the safety net for bootstrap (no triage
    # has ever acked) and stuck-signal cases (process crashed mid-emit,
    # signal lost). Kicks scout only when sift's inbox has run dry —
    # if sift still has issue cards to screen, the substrate has
    # plenty to do and another search would just pile on. Scout's
    # SkillActor dedupes msg_ids, so a leaked extra card is benign.
    try:
        from sweep.activities.scout import kick_scout_card, SCOUT_INBOX
        from sweep.activities.scout import SIFT_INBOX
        from sweep import inbox_state as _inbox
        sift_q = len(_inbox.inbox_states("sift")["queued"]) \
            if SIFT_INBOX.exists() else 0
        scout_q = len(_inbox.inbox_states("scout")["queued"]) \
            if SCOUT_INBOX.exists() else 0
        if sift_q == 0 and scout_q == 0:
            wf_id = await kick_scout_card("leakdog-heartbeat")
            out["scout_heartbeat"] = "fired" if wf_id else "fired-no-signal"
        else:
            out["scout_heartbeat"] = (
                f"skip (sift={sift_q}, scout={scout_q})"
            )
    except Exception as e:
        out["scout_heartbeat_error"] = f"{type(e).__name__}: {str(e)[:200]}"

    # --- (4) Human inbox staleness refresh ------------------------
    # When the operator answers a maintainer's question on GitHub,
    # the PR's bucket flips away from "human" but our inbox entry
    # lingers until either the maintainer replies (notification poller
    # catches it) or the seeder rescan runs. Leakdog closes
    # that gap: re-fetch the PR (5min TTL cache, so this batches
    # cheaply across ticks) and ack inbox entries whose precondition
    # no longer holds.
    try:
        refreshed = await _refresh_human_inbox()
        out["human_refreshed"] = refreshed
    except Exception as e:
        out["human_error"] = f"{type(e).__name__}: {str(e)[:200]}"

    # --- (5) Unclassified-PR seed ---------------------------------
    # The notification poller is push-shaped — it only sees PRs whose
    # state changed *while* it was running. A PR that's been sitting
    # in CHANGES_REQUESTED for days with no fresh notification stays
    # invisible to the substrate. Leakdog's pull-shaped tick finds
    # open PRs not currently in any inbox and kicks them into remit
    # for classify-and-route. Bounded by gh_io.search_prs cache.
    try:
        seeded = await _seed_unclassified_prs()
        out["unclassified_seeded"] = seeded
    except Exception as e:
        out["unclassified_seed_error"] = f"{type(e).__name__}: {str(e)[:200]}"

    return out


async def _seed_unclassified_prs() -> dict:
    """Find open PRs not in any actor inbox; kick remit to classify.
    Returns {open, in_inbox, seeded}. Caps seeds per tick to bound
    remit-queue depth — under typical load (~few stale PRs/day) this
    drains in one tick; on backfill it spreads across several."""
    import json
    from pathlib import Path
    from sweep import gh_io
    from sweep.activities.remit import kick_remit_card

    SEED_CAP = 20

    try:
        prs = gh_io.search_prs("--author=@me", state="open", limit=200)
    except Exception:
        prs = []
    if not prs:
        return {"open": 0, "in_inbox": 0, "seeded": 0}

    # Build "seen" set from every actor inbox file (queued + acked).
    # If any past inbox entry exists for (repo, pr), don't re-kick;
    # remit owns the freshness decision via its own re-fetch.
    inbox_dir = Path.home() / ".sweep" / "inbox"
    seen: set[tuple] = set()
    for p in inbox_dir.glob("*.jsonl"):
        if p.name.startswith("_") or ".dry." in p.name:
            continue
        try:
            for line in p.read_text().splitlines():
                if not line.strip():
                    continue
                try:
                    m = json.loads(line)
                    repo, pr = m.get("repo"), m.get("pr")
                    if repo and pr:
                        seen.add((repo, int(pr)))
                except Exception:
                    pass
        except OSError:
            pass

    seeded = 0
    for pr_data in prs:
        if seeded >= SEED_CAP:
            break
        url = pr_data.get("url", "")
        if not url:
            continue
        # url shape: https://github.com/owner/repo/pull/123
        parts = url.replace("https://github.com/", "").split("/")
        if len(parts) < 4:
            continue
        repo = f"{parts[0]}/{parts[1]}"
        try:
            pr_num = int(parts[3])
        except ValueError:
            continue
        if (repo, pr_num) in seen:
            continue
        await kick_remit_card(repo, pr_num, sender="leakdog-seed")
        seeded += 1

    return {"open": len(prs), "in_inbox": len(seen), "seeded": seeded}


async def _refresh_human_inbox() -> dict:
    """For each unique (repo, pr) in the human inbox's queued set,
    re-fetch the PR state and ack the msg if the bucket has moved
    away from 'human'. Returns counts for the tick log."""
    import json
    from pathlib import Path
    from sweep import gh_io
    from sweep.activities.pr_state import classify_one_pr
    from sweep.types import PrLiveState

    inbox_path = Path.home() / ".sweep" / "inbox" / "human.jsonl"
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
    #
    # ONLY consider cards whose sender == "remit" — those are pure
    # bucket-mirroring cards (remit classified to human; if the bucket
    # has since moved, ack). Cards from other senders (dco-batch,
    # investigate, manual-backfill, sign actor's _kick_human_decision)
    # represent operator-action requests that survive until the operator
    # acks them. Leakdog acking those was the 2026-05-18 leak where
    # dco-pushready cards kept getting re-acked despite the force-push
    # never having been executed.
    by_pr: dict[tuple, list[str]] = {}
    for line in inbox_path.read_text().splitlines():
        if not line.strip(): continue
        try:
            m = json.loads(line)
        except Exception:
            continue
        if m.get("msg_id") in acked:
            continue
        if m.get("sender") != "remit":
            continue  # operator-action card; not leakdog's to ack
        repo, pr = m.get("repo"), m.get("pr")
        if not repo or not pr:
            continue
        by_pr.setdefault((repo, pr), []).append(m.get("msg_id"))

    if not by_pr:
        return {"checked": 0, "acked": 0}

    import datetime as _dt
    from sweep.activities.pr_state import gh_pr_view
    now_iso = _dt.datetime.now(_dt.timezone.utc).isoformat()
    new_acks: list[str] = []
    for (repo, pr), msg_ids in by_pr.items():
        try:
            # Use the real gh_pr_view (not a stub) so maintainer_question
            # and maintainer_raised_concern get derived honestly. The stub
            # `_live_state_from_gh` passed False for those, which caused
            # leakdog to ack human-bucket cards that were created via the
            # LLM-judged paths — silently dropping work that still needed
            # the human. gh_io.pr_view's 5-min cache is shared, so the gh
            # fetch is still cheap across the tick.
            live = await gh_pr_view(repo, pr)
        except Exception:
            continue
        if live is None:
            continue
        try:
            result = await classify_one_pr(live)
        except Exception:
            continue
        if result.bucket == "human":
            continue  # still human's court; leave it
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


# ------------------------------------------------------------------- comment-issue
# 7-day window per [[H23]]. If no maintainer engagement inside this
# window, the comment is considered muted — a real signal, not a leak.
TISSUE_WATCH_DAYS = 7


async def _tissue_engagement_sweep() -> dict:
    """Walk posted-comment-issue state, poll each issue for activity since
    post_ts. Promote to `engaged` on first activity; promote to `muted`
    when the 7-day window closes silent. Idempotent — state file
    tracks status so a comment-issue is never engaged/muted twice."""
    import datetime as _dt
    import json as _json
    from pathlib import Path
    from sweep import gh_io, observe

    state_path = Path.home() / ".sweep" / "state" / "comment_issue_posted.json"
    if not state_path.exists():
        return {"watching": 0, "engaged": 0, "muted": 0}

    try:
        state: dict = _json.loads(state_path.read_text())
    except (OSError, _json.JSONDecodeError):
        return {"watching": 0, "engaged": 0, "muted": 0, "error": "state_unreadable"}

    now = _dt.datetime.now(_dt.timezone.utc)
    window = _dt.timedelta(days=TISSUE_WATCH_DAYS)
    counts = {"watching": 0, "engaged": 0, "muted": 0}

    try:
        u = gh_io.api("user", ttl=86400)
        me = (u.get("login") if isinstance(u, dict) else "") or ""
    except Exception:
        me = ""

    changed = False
    for draft_id, entry in list(state.items()):
        if entry.get("status") != "watching":
            continue
        try:
            posted_at = _dt.datetime.fromisoformat(entry.get("posted_at", ""))
        except (ValueError, AttributeError):
            continue
        repo = entry.get("repo", "")
        issue = entry.get("issue", 0)
        if not repo or not issue:
            continue
        # Pull issue + its comments. Filter for activity strictly
        # after posted_at, by anyone other than us.
        engaged = False
        engagement_reply_text = ""
        engagement_reply_author = ""
        engagement_comment_url = ""
        try:
            comments = gh_io.api(
                f"repos/{repo}/issues/{issue}/comments",
                ttl=300,
            )
        except Exception:
            comments = None
        if isinstance(comments, list):
            for c in comments:
                try:
                    c_at = _dt.datetime.fromisoformat(
                        (c.get("created_at") or "").replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    continue
                if c_at <= posted_at:
                    continue
                author = (c.get("user") or {}).get("login", "")
                if author and author != me:
                    engaged = True
                    engagement_reply_text = c.get("body", "") or ""
                    engagement_reply_author = author
                    engagement_comment_url = c.get("html_url", "") or ""
                    break
        # Issue-level signals: closed, reactions, labels.
        if not engaged:
            try:
                issue_d = gh_io.api(
                    f"repos/{repo}/issues/{issue}",
                    ttl=300,
                )
            except Exception:
                issue_d = None
            if isinstance(issue_d, dict):
                # Issue closed after our post → engagement
                if issue_d.get("state") == "closed":
                    try:
                        closed_at = _dt.datetime.fromisoformat(
                            (issue_d.get("closed_at") or "").replace("Z", "+00:00"))
                        if closed_at > posted_at:
                            engaged = True
                    except (ValueError, AttributeError):
                        pass
                if not engaged and (issue_d.get("reactions") or {}).get("total_count", 0) > 0:
                    # Reactions don't have timestamps in the issue payload;
                    # treat any > 0 as a soft engagement signal post-watch-start.
                    # Conservative — false positives are tolerable here.
                    engaged = True

        if engaged:
            entry["status"] = "engaged"
            entry["engaged_at"] = now.isoformat()
            observe.event("tissue_engaged", draft_id=draft_id,
                          repo=repo, issue=issue,
                          comment_url=entry.get("comment_url", ""),
                          days_to_engage=(now - posted_at).total_seconds() / 86400.0)
            counts["engaged"] += 1
            changed = True
            # If the engagement was a textual reply (not just a close
            # or reaction), hand it to bless to classify and route.
            if engagement_reply_text.strip():
                try:
                    from sweep.activities.bless import kick_bless_card
                    await kick_bless_card(
                        repo=repo, issue=issue,
                        tissue_draft_id=draft_id,
                        reply_text=engagement_reply_text,
                        reply_author=engagement_reply_author,
                        comment_url=engagement_comment_url,
                    )
                except Exception as e:
                    observe.event("kick_bless_failed",
                                  repo=repo, issue=issue,
                                  draft_id=draft_id,
                                  error_type=type(e).__name__,
                                  error=str(e)[:200])
        elif now - posted_at > window:
            entry["status"] = "muted"
            entry["muted_at"] = now.isoformat()
            observe.event("tissue_muted", draft_id=draft_id,
                          repo=repo, issue=issue,
                          comment_url=entry.get("comment_url", ""))
            counts["muted"] += 1
            changed = True
        else:
            counts["watching"] += 1

    if changed:
        try:
            state_path.write_text(_json.dumps(state))
        except OSError:
            pass
    return counts
