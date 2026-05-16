"""Claim an issue — post a short "I'm on this" comment via gh.

Earliest defensible moment: after /investigate's pushout converges
on a concrete fix shape. The hypothesis is grounded, no worktree has
been touched yet, no PR opened. Posting now reserves the first-mover
spot we already grabbed via recency-first prospect.

Gated per-repo via `retro_params`: `claim_after_investigate=true|false`,
default false (cautious — some communities discourage claiming, the
operator opts in per repo from CONTRIBUTING signals). Honors dry mode:
under dry, the comment is logged to events.jsonl but not actually
posted, so the operator can rehearse the claim text.

Asymmetric risk: claim-then-ghost is worse than never having claimed,
because the maintainer remembers the unfilled promise. The retro_param
default of false is the conservative side.
"""

from __future__ import annotations

import asyncio
import subprocess

from temporalio import activity
from temporalio.exceptions import ApplicationError

from sweep import control_state, observe, retro_params


@activity.defn
async def claim_issue(repo: str, issue: int, hypothesis_summary: str) -> dict:
    """Post a short claim comment on the issue if the per-repo
    retro_param permits it. Returns a dict describing what happened —
    one of {state: "claimed"|"skipped_param"|"dry_skip"|"failed"}.

    Always non-blocking on success/failure: claim failures don't halt
    the actor (they're not contract violations, just a missed
    opportunity). The downstream pipeline proceeds either way.
    """
    if not repo or not issue:
        raise ApplicationError("claim_issue: repo + issue required",
                               non_retryable=True)
    summary = (hypothesis_summary or "").strip()
    if not summary:
        raise ApplicationError("claim_issue: empty hypothesis summary",
                               non_retryable=True)

    allow = retro_params.resolved(repo).get("claim_after_investigate")
    if not allow:
        observe.event("claim_skipped", repo=repo, issue=issue,
                      reason="retro_param off")
        return {"state": "skipped_param", "repo": repo, "issue": issue}

    body = (
        f"Looking at this — {summary[:280]}\n\n"
        "Will open a PR shortly if the fix shape holds."
    )

    if control_state.is_dry():
        observe.event("claim_dry_skip", repo=repo, issue=issue,
                      body_preview=body[:160])
        return {"state": "dry_skip", "repo": repo, "issue": issue,
                "would_post": body}

    cmd = ["gh", "issue", "comment", str(issue),
           "--repo", repo, "--body", body]
    try:
        result = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True, timeout=60,
        )
    except FileNotFoundError as e:
        observe.event("claim_failed", repo=repo, issue=issue,
                      reason=f"gh not on PATH: {e}")
        return {"state": "failed", "reason": str(e)}
    except subprocess.TimeoutExpired:
        observe.event("claim_failed", repo=repo, issue=issue,
                      reason="gh issue comment timed out")
        return {"state": "failed", "reason": "timeout"}
    if result.returncode != 0:
        observe.event("claim_failed", repo=repo, issue=issue,
                      reason=(result.stderr or "")[:200])
        return {"state": "failed", "reason": (result.stderr or "")[:200]}

    observe.event("issue_claimed", repo=repo, issue=issue,
                  body_preview=body[:160])
    return {"state": "claimed", "repo": repo, "issue": issue,
            "comment_url": (result.stdout or "").strip()}
