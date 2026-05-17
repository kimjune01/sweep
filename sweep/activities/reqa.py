"""Reqa — engagement-lane qa verification.

Same qa pipeline (test_attestation + codex_review + gemini_review +
verdict resolution), different application: reqa runs on follow-up
patches pushed to existing PRs. Skips the production-lane compose +
submit gates because the PR already exists; on verdict=pass, kicks
respond-actor to push the patch to the existing branch.

Precondition: msg.pr required. Without one this card was misrouted —
the production lane's qa-actor handles new-PR verifications.

The qa skill code itself is unchanged. Reqa is a SkillActor (not
QaActor) because engagement traffic is low — no need for the
concurrent-dispatcher shape. If the load profile ever justifies
concurrency, reqa graduates to its own ReqaActor workflow class.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict
from pathlib import Path

from temporalio import activity
from temporalio.exceptions import ApplicationError

from sweep.types import Message, QaOneEntryRequest


REQA_INBOX = Path.home() / ".sweep" / "inbox" / "reqa.jsonl"


@activity.defn
async def kick_reqa_card(repo: str, pr: int,
                         branch: str | None = None,
                         sender: str = "reinvestigate",
                         attestation_hash: str | None = None) -> str | None:
    """Deposit a reqa card on reqa.jsonl and signal reqa-actor.
    Called by reinvestigate after producing a follow-up patch, OR by
    remit when CI fails with a mechanical-fix check on an existing PR."""
    from sweep import observe
    from sweep.activities.pr_state import _signal_actor

    ts = dt.datetime.now(dt.timezone.utc)
    slug = repo.replace("/", "-")
    msg_id = f"reqa-{ts.strftime('%Y%m%dT%H%M%S')}-{slug}-{pr}"
    payload: dict = {}
    if attestation_hash:
        payload["attestation_hash"] = attestation_hash
    msg = Message(
        msg_id=msg_id,
        sender=sender,
        intent="reattest-followup",
        repo=repo,
        pr=pr,
        branch=branch,
        payload=payload,
        ts=ts.isoformat(),
    )
    REQA_INBOX.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(REQA_INBOX, "a") as f:
            f.write(json.dumps(asdict(msg)) + "\n")
    except Exception as e:
        observe.event("reqa_card_write_failed", repo=repo, pr=pr,
                      error_type=type(e).__name__, error=str(e)[:200])
        return None
    observe.event("reqa_card_deposited", repo=repo, pr=pr,
                  sender=sender, msg_id=msg_id)
    return await _signal_actor("reqa", msg)


@activity.defn
async def reqa_cycle(msg: Message) -> dict:
    """Verify a follow-up patch on an existing PR; on pass, kick respond.

    Precondition: msg.pr required. msg.branch should carry the patched
    branch (provided by reinvestigate); if absent we fall back to the
    PR's headRefName via gh.
    """
    if not msg.pr:
        raise ApplicationError(
            "reqa: msg.pr required (engagement-lane only); "
            "new-PR verifications belong on qa.jsonl",
            non_retryable=True,
        )

    from sweep import observe
    from sweep.activities.qa import qa_one_entry
    from sweep.activities.worktree import ensure_worktree
    from sweep.activities.infer import infer_test_cmd
    from sweep.activities.respond import kick_respond_card

    branch = msg.branch
    if not branch:
        # Fallback: read the PR's headRefName. Reinvestigate normally
        # populates msg.branch, but a manual kick or a stale upstream
        # might not.
        from sweep.activities.pr_state import gh_pr_view
        live = await gh_pr_view(msg.repo, int(msg.pr))
        branch = live.branch
        if not branch:
            raise ApplicationError(
                f"reqa: cannot resolve branch for {msg.repo}#{msg.pr}",
                non_retryable=True,
            )

    worktree = await ensure_worktree(msg.repo, branch)
    test_cmd = await infer_test_cmd(worktree, msg.repo)

    req = QaOneEntryRequest(
        msg_id=msg.msg_id,
        repo=msg.repo,
        branch=branch,
        worktree=worktree,
        test_cmd=test_cmd,
        issue=int(msg.pr),
    )
    result = await qa_one_entry(req)
    observe.event(
        "reqa_converged",
        repo=msg.repo,
        pr=msg.pr,
        verdict=result.verdict,
        msg_id=msg.msg_id,
    )

    if result.verdict == "pass":
        try:
            await kick_respond_card(
                msg.repo, branch, pr=int(msg.pr),
                sender="reqa",
            )
        except Exception as e:
            observe.event("kick_respond_failed", repo=msg.repo, pr=msg.pr,
                          error_type=type(e).__name__, error=str(e)[:200])

    return {
        "verdict": result.verdict,
        "branch": branch,
        "msg_id": msg.msg_id,
    }
