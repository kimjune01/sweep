"""PR-state activities — classify open authored PRs into buckets and
deliver one message per PR to the matching downstream actor's inbox.

Each activity is independently callable for development in isolation.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
from dataclasses import asdict
from pathlib import Path

from temporalio import activity
from temporalio.exceptions import ApplicationError

from sweep.io_safe import atomic_write_text
from sweep.types import (
    BUCKET_ROUTING,
    Message,
    PrLiveState,
    PrStateResult,
)

INBOX_DIR = Path.home() / ".sweep" / "inbox"


# ------------------------------------------------------------ gh wrappers


@activity.defn
async def gh_search_open_authored(limit: int = 50) -> list[dict]:
    """List my open PRs across GitHub. Returns minimal fields; callers fetch
    detail per PR via gh_pr_view."""
    user = subprocess.run(
        ["gh", "api", "user", "--jq", ".login"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    out = subprocess.run(
        [
            "gh", "search", "prs",
            "--author", user,
            "--state", "open",
            "--limit", str(limit),
            "--json", "repository,number,title,url,createdAt,updatedAt,author",
        ],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout or "[]")


@activity.defn
async def gh_pr_view(repo: str, pr: int) -> PrLiveState:
    """Pull live state for one PR. Independently callable for development."""
    if "/" not in repo:
        raise ApplicationError("repo must be owner/repo", non_retryable=True)
    out = subprocess.run(
        [
            "gh", "pr", "view", str(pr),
            "--repo", repo,
            "--json",
            "state,mergeable,reviewDecision,reviews,statusCheckRollup,isDraft,"
            "comments,headRefName,updatedAt,title,url",
        ],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise ApplicationError(
            f"gh pr view failed: {out.stderr[:300]}",
            non_retryable=False,  # transient — retryable
        )
    data = json.loads(out.stdout)

    # CI derivation
    rollup = data.get("statusCheckRollup") or []
    failing = next(
        (c.get("name", "") for c in rollup if c.get("conclusion") == "FAILURE"),
        "",
    )
    if failing:
        ci = "failing"
    elif rollup and any(c.get("status") != "COMPLETED" for c in rollup):
        ci = "pending"
    elif rollup and all(c.get("conclusion") == "SUCCESS" for c in rollup):
        ci = "green"
    else:
        ci = "unknown"

    # activity_h
    updated = dt.datetime.fromisoformat(data["updatedAt"].replace("Z", "+00:00"))
    now = dt.datetime.now(dt.timezone.utc)
    activity_h = (now - updated).total_seconds() / 3600.0

    # maintainer_question — did a MEMBER/OWNER/COLLABORATOR comment after our
    # last commit, with a "?" in the body?
    comments = data.get("comments") or []
    maintainer_question = any(
        c.get("authorAssociation") in ("MEMBER", "OWNER", "COLLABORATOR")
        and "?" in (c.get("body") or "")
        for c in comments
    )

    return PrLiveState(
        repo=repo,
        pr=pr,
        branch=data.get("headRefName", ""),
        title=data.get("title", ""),
        url=data.get("url", ""),
        review_decision=data.get("reviewDecision") or "",
        mergeable=data.get("mergeable") or "",
        ci=ci,
        activity_h=activity_h,
        maintainer_question=maintainer_question,
        is_draft=bool(data.get("isDraft")),
        failing_check=failing,
    )


# ------------------------------------------------------------ classifier


def _msg_id(repo: str, pr: int, ts_minute: str) -> str:
    slug = repo.replace("/", "-")
    return f"prstate-{ts_minute}-{slug}-{pr}"


@activity.defn
async def classify_one_pr(state: PrLiveState) -> PrStateResult:
    """Pure-ish classifier: bucket rules applied in priority order."""
    rd = state.review_decision
    ci = state.ci
    merge = state.mergeable
    reasons: list[str] = []

    # 1. close (terminal — needs explicit signal, not stale-age)
    #    We only auto-flag close for: changes_requested + close-this-PR-language.
    #    Superseded-PR detection lives elsewhere; not enough signal here yet.
    #    So close is rarely chosen — that's per the user's "never recommend
    #    closing a stale PR" rule.

    # 2. investigate
    if rd == "CHANGES_REQUESTED" or state.maintainer_question:
        bucket = "investigate"
        reasons.append(
            "changes_requested" if rd == "CHANGES_REQUESTED" else "maintainer asked"
        )
    # 3. rebase
    elif merge == "CONFLICTING":
        bucket = "rebase"
        reasons.append("merge conflicts")
    # 4. qa
    elif ci == "failing":
        bucket = "qa"
        reasons.append(f"CI failure: {state.failing_check or 'unspecified'}")
    # 5. ship
    elif rd == "APPROVED" and merge == "MERGEABLE" and ci == "green":
        bucket = "ship"
        reasons.append("approved + mergeable + green CI")
    # 6. wait (default)
    else:
        bucket = "wait"
        reasons.append("no action signal")

    return PrStateResult(
        repo=state.repo,
        pr=state.pr,
        branch=state.branch,
        bucket=bucket,
        signals={
            "review": rd,
            "mergeable": merge,
            "ci": ci,
            "activity_h": round(state.activity_h, 1),
            "failing_check": state.failing_check,
            "maintainer_question": state.maintainer_question,
        },
        reason="; ".join(reasons),
    )


# ------------------------------------------------------------ inbox delivery


@activity.defn
async def deliver_to_inbox(result: PrStateResult) -> str:
    """Append one message to the bucket's destination inbox. Returns the path
    written. Idempotent via msg_id — same minute, same bucket, same PR ⇒ same
    msg_id ⇒ receivers dedupe."""
    actor, intent = BUCKET_ROUTING[result.bucket]
    ts = dt.datetime.now(dt.timezone.utc)
    ts_minute = ts.strftime("%Y-%m-%dT%H:%MZ")

    msg = Message(
        msg_id=_msg_id(result.repo, result.pr, ts_minute),
        sender="pr-state",
        intent=intent,
        repo=result.repo,
        pr=result.pr,
        branch=result.branch,
        payload={
            "bucket": result.bucket,
            "signals": result.signals,
            "reason": result.reason,
        },
        ts=ts.isoformat(),
    )

    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    inbox = INBOX_DIR / f"{actor}.jsonl"
    line = json.dumps(asdict(msg)) + "\n"
    # Append-only — read all lines later, dedupe by msg_id.
    with open(inbox, "a") as f:
        f.write(line)
    return str(inbox)
