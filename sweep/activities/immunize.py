"""Immunize — anti-AI repo routing.

Defense-in-depth gate for repos with hostile AI policies. Sift's
`_passes_lightweight_filter` already drops them at the front of the
funnel and seeds `slop_offer_seeds.txt`, but the AI-policy cache has
a 24h TTL and operator-curated kill list may lag — issues can leak
through to triage from repos that have since added an AI-hostile
policy.

When that happens, triage_cycle re-checks the live policy and routes
the card here instead of letting investigate burn cycles on it. The
activity does not investigate, comment, or otherwise contact the repo
— it only re-seeds the slop-offer pipeline (which already exists as
the deliberate-outreach surface for these repos, human-gated).

Per [[O4]]: this actor's job is to be boring. If it never fires,
sift's gate is doing its job. If it fires often, sift's gate
is broken and should be tightened upstream — fix the gate, don't lean
on the safety net.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict
from pathlib import Path

from temporalio import activity
from temporalio.exceptions import ApplicationError

from sweep import gh_io, observe, slop_offer_seed
from sweep.types import Message, forward_ledger


IMMUNIZE_INBOX = Path.home() / ".sweep" / "inbox" / "immunize.jsonl"


async def kick_immunize_card(repo: str, issue: int | None, *,
                              source: str,
                              incoming: Message | None = None) -> str | None:
    """Deposit an anti-AI card on the immunize inbox and signal the
    actor. Called from sift (repo-level, issue=None) and from
    triage (issue-level, issue=number).

    The activity does the live policy re-check + seeding; this helper
    is just the routing call. Idempotent at the actor (msg_id
    dedupes); the seed file is also dedup-on-read so multiple kicks
    for the same repo collapse to one slop-offer candidate.
    """
    from sweep.activities.pr_state import _signal_actor
    ts = dt.datetime.now(dt.timezone.utc)
    issue_part = str(issue) if issue else "repo"
    msg = Message(
        msg_id=f"immunize-{repo.replace('/', '-')}-{issue_part}-"
               f"{ts.strftime('%Y%m%dT%H%M%S')}",
        sender=source,
        intent="anti-ai",
        repo=repo, pr=issue, branch=None,
        payload={"source": source},
        ts=ts.isoformat(),
        ledger=forward_ledger(incoming),
    )
    IMMUNIZE_INBOX.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(IMMUNIZE_INBOX, "a") as f:
            f.write(json.dumps(asdict(msg)) + "\n")
    except OSError as e:
        observe.event("immunize_card_write_failed", repo=repo,
                      issue=issue, error_type=type(e).__name__,
                      error=str(e)[:200])
        return None
    observe.event("immunize_card_deposited", repo=repo, issue=issue,
                  source=source, msg_id=msg.msg_id)
    return await _signal_actor("immunize", msg)


@activity.defn
async def immunize_cycle(msg: Message) -> dict:
    """Route one anti-AI card into the slop-offer pipeline.

    Emits exactly one terminal event:
      - immunize_redirected (seeded=bool) — card handled, repo added
        to slop-offer seed (or already present)
      - immunize_skipped (reason) — defense-in-depth re-check found
        the repo isn't actually hostile (cache resettled, policy
        changed); card drops without seeding to avoid false positives
    """
    if not msg.repo:
        raise ApplicationError("immunize: repo required",
                               non_retryable=True)
    repo = msg.repo
    from sweep import budget as _budget
    _budget.set_caller("triage")  # cost class — one gh policy re-check

    # Defense-in-depth re-check: confirm the repo is still hostile at
    # the moment of routing. Triage's upstream check may have fired on
    # a now-stale cache.
    try:
        policy = gh_io.repo_ai_policy(repo, ttl=0)  # force refresh
    except Exception as e:
        observe.event("immunize_skipped", repo=repo, issue=msg.pr,
                      reason=f"policy_check_failed:{type(e).__name__}")
        return {"skipped": "policy_check_failed", "error": str(e)[:200]}
    if policy != "hostile":
        observe.event("immunize_skipped", repo=repo, issue=msg.pr,
                      reason=f"policy_resettled:{policy}")
        return {"skipped": "policy_resettled", "policy": policy}

    # Worth-pursuing decision: not every hostile repo is a good
    # slop-offer target. Filter on minimum signal (visibility) and
    # avoid re-seeding the same repo over and over (already in the
    # pipeline). Cheap heuristics; richer judgment can come later.
    decision = _worth_pursuing(repo)
    if not decision["pursue"]:
        observe.event("immunize_skipped", repo=repo, issue=msg.pr,
                      reason=decision["reason"], policy=policy)
        return {"redirected": True, "seeded": False,
                "reason": decision["reason"]}

    # Two output paths based on whether we have a specific issue:
    #   - issue-level (triage source): draft a deferential
    #     acknowledgement, route through tissue-drafts → post so the
    #     operator approval gate applies the same way as tissue.
    #   - repo-level (sift source, no issue): append to the
    #     legacy slop_offer_seeds file. The existing `sweep slop-offer`
    #     CLI flow consumes these for repo-level outreach.
    if msg.pr:
        draft_id = _draft_acknowledgement_to_tissue(
            repo=repo, issue=int(msg.pr),
            source=(msg.sender or "unknown"),
            policy=policy,
        )
        observe.event("immunize_redirected", repo=repo, issue=msg.pr,
                      seeded=False, drafted=True,
                      draft_id=draft_id,
                      source=(msg.sender or "unknown"),
                      reason=decision["reason"],
                      ts=dt.datetime.now(dt.timezone.utc).isoformat())
        return {"redirected": True, "seeded": False,
                "drafted": True, "draft_id": draft_id,
                "reason": decision["reason"]}

    # Repo-level: legacy seed path. Operator runs `sweep slop-offer`
    # to process these.
    slop_offer_seed.append(repo)
    observe.event("immunize_redirected", repo=repo, issue=None,
                  seeded=True, drafted=False,
                  source=(msg.sender or "unknown"),
                  reason=decision["reason"],
                  ts=dt.datetime.now(dt.timezone.utc).isoformat())
    return {"redirected": True, "seeded": True, "repo": repo,
            "reason": decision["reason"]}


def _draft_acknowledgement_to_tissue(*, repo: str, issue: int,
                                      source: str, policy: str) -> str:
    """Draft a templated deferential acknowledgement and write it to
    tissue-drafts. The operator approves via the same `sweep tissue`
    CLI; post posts. Template-only for the first batch — the message
    is simple enough that variance doesn't help, and a uniform tone
    across slop-offer outreach reads as a coherent policy rather than
    a per-repo improvisation.

    Returns the draft_id so the immunize event can carry it forward."""
    from sweep.activities.tissue import TISSUE_DRAFTS
    ts = dt.datetime.now(dt.timezone.utc)
    draft_id = (f"immunize-{repo.replace('/', '-')}-{issue}-"
                f"{ts.strftime('%Y%m%dT%H%M%S')}")
    comment = (
        f"Noticed this repo has an AI-contribution policy "
        f"(detected: {policy}). Stepping back on this issue per your "
        f"policy. If you'd ever like a different shape of collaboration "
        f"(review or filter rather than code), let me know."
    )
    draft = {
        "draft_id":    draft_id,
        "repo":        repo,
        "issue":       issue,
        "comment":     comment,
        "draft_chars": len(comment),
        "artifact":    "",
        "drafted_at":  ts.isoformat(),
        "source_card": f"immunize:{source}",
        "signal":      "slop-offer",
    }
    TISSUE_DRAFTS.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(TISSUE_DRAFTS, "a") as f:
            f.write(json.dumps(draft) + "\n")
    except OSError as e:
        observe.event("immunize_draft_write_failed",
                      repo=repo, issue=issue,
                      error_type=type(e).__name__, error=str(e)[:200])
        return ""
    return draft_id


# Minimum stars to bother with slop-offer outreach. Below this, the
# repo doesn't have the visibility that makes slop-offer's framing
# pay off — small / dead repos waste the operator's review time.
IMMUNIZE_MIN_STARS = 500

# How long to suppress re-seeding the same repo. The slop-offer flow
# is operator-paced; flooding the seed file with the same repo every
# time sift (or triage) catches it again is noise.
IMMUNIZE_SEED_TTL_DAYS = 30


def _worth_pursuing(repo: str) -> dict:
    """Heuristic-only: does this repo meet the bar for slop-offer
    outreach? Returns `{pursue: bool, reason: str}` so the operator
    can read why immunize routed (or didn't) without diving into
    the activity."""
    # Dedupe against recent seeds — if it's already in the file from
    # the last 30 days, don't re-add. slop_offer_seed itself dedupes
    # on read so this is mostly about event noise, not correctness.
    try:
        existing = set(slop_offer_seed.read_unique())
    except Exception:
        existing = set()
    if repo in existing:
        return {"pursue": False, "reason": "already_seeded"}

    # Visibility gate: pull the lite repo meta (cached 24h) and
    # require min stars. The cache means this is ~free in steady state.
    try:
        meta = gh_io._cached_json(
            "repo_view_lite",
            ["api", f"repos/{repo}", "--jq",
             "{stars: .stargazers_count, archived: .archived, "
             "pushed_at: .pushed_at}"],
            ttl=24 * 3600,
        )
    except Exception:
        # Fail-soft: if we can't fetch meta, assume not worth pursuing.
        # Better to undercount slop-offer candidates than over-noise the
        # operator with repos we know nothing about.
        return {"pursue": False, "reason": "meta_unavailable"}

    if not isinstance(meta, dict):
        return {"pursue": False, "reason": "meta_malformed"}
    if meta.get("archived"):
        return {"pursue": False, "reason": "archived"}
    stars = int(meta.get("stars", 0) or 0)
    if stars < IMMUNIZE_MIN_STARS:
        return {"pursue": False,
                "reason": f"below_min_stars:{stars}<{IMMUNIZE_MIN_STARS}"}

    # Pushed-at recency: dead repos waste outreach.
    pushed = meta.get("pushed_at")
    if pushed:
        try:
            t = dt.datetime.fromisoformat(pushed.replace("Z", "+00:00"))
            if (dt.datetime.now(dt.timezone.utc) - t).days > 365:
                return {"pursue": False, "reason": "stale_pushed_at"}
        except (ValueError, AttributeError):
            pass

    return {"pursue": True,
            "reason": f"visible:{stars}_stars"}
