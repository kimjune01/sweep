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

from sweep import gh_io, models
from sweep.io_safe import atomic_write_text
from sweep.types import (
    BUCKET_ROUTING,
    Message,
    PrLiveState,
    PrStateResult,
)

# pr-state shuffles work — picks bucket, routes intent. Sonnet by default.
PR_STATE_MODEL = models.default_for("orchestrate")

INBOX_DIR = Path.home() / ".sweep" / "inbox"
CLASSIFIED_INBOX = INBOX_DIR / "classified.jsonl"


# ------------------------------------------------------------ gh wrappers


@activity.defn
async def gh_search_open_authored(limit: int = 50) -> list[dict]:
    """List my open PRs across GitHub. Returns minimal fields; callers fetch
    detail per PR via gh_pr_view."""
    user = subprocess.run(
        ["gh", "api", "user", "--jq", ".login"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return gh_io.search_prs(
        f"author:{user}",
        state="open",
        limit=limit,
        fields="repository,number,title,url,createdAt,updatedAt,author",
        ttl=60,
    )


@activity.defn
async def gh_pr_view(repo: str, pr: int) -> PrLiveState:
    """Pull live state for one PR. Independently callable for development."""
    if "/" not in repo:
        raise ApplicationError("repo must be owner/repo", non_retryable=True)
    try:
        data = gh_io.pr_view(repo, pr, ttl=60)
    except subprocess.CalledProcessError as e:
        raise ApplicationError(
            f"gh pr view failed: {(e.stderr or '')[:300]}",
            non_retryable=False,  # transient — retryable
        )
    if not data:
        raise ApplicationError(
            f"gh pr view returned empty for {repo}#{pr}",
            non_retryable=False,
        )

    # Inline code-review comments live on a separate REST endpoint
    # (not exposed via `gh pr view --json`).
    try:
        data["_inline_comments"] = gh_io.pr_inline_comments(repo, pr)
    except Exception:
        data["_inline_comments"] = []

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

    # 2. respondable — reviewer engaged, ball back in human's court
    if rd == "CHANGES_REQUESTED" or state.maintainer_question:
        bucket = "respondable"
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
async def deposit_classified(result: PrStateResult) -> str:
    """Write one PrStateResult to classified.jsonl as the unrouted record.

    Routing happens later (route_classified). Decoupling classification
    from routing means rule changes don't require re-classifying — and
    once Sonnet is wired into classify_reviews, that's the expensive part
    we don't want to repay.
    """
    ts = dt.datetime.now(dt.timezone.utc)
    record = {
        "ts": ts.isoformat(),
        "repo": result.repo,
        "pr": result.pr,
        "branch": result.branch,
        "bucket": result.bucket,
        "signals": result.signals,
        "reason": result.reason,
    }
    CLASSIFIED_INBOX.parent.mkdir(parents=True, exist_ok=True)
    with open(CLASSIFIED_INBOX, "a") as f:
        f.write(json.dumps(record) + "\n")
    return str(CLASSIFIED_INBOX)


@activity.defn
async def route_classified() -> dict:
    """Read classified.jsonl, route each PR to its bucket's inbox.

    Runs on its own takt — cheap, rule-based, can re-run if routing logic
    changes. Idempotent per (repo, pr) within a minute via msg_id dedup.
    """
    if not CLASSIFIED_INBOX.exists():
        return {"read": 0, "routed": {}, "skipped_acked": 0}

    # Dedup: latest record per (repo, pr).
    latest: dict[tuple[str, int], dict] = {}
    for line in CLASSIFIED_INBOX.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
            latest[(r["repo"], r["pr"])] = r
        except (json.JSONDecodeError, KeyError):
            pass

    routed: dict[str, int] = {}
    for (repo, pr), r in latest.items():
        bucket = r.get("bucket", "wait")
        actor, intent = BUCKET_ROUTING.get(bucket, ("retro", "audit"))
        ts = dt.datetime.now(dt.timezone.utc)
        ts_minute = ts.strftime("%Y-%m-%dT%H:%MZ")
        slug = repo.replace("/", "-")
        msg = Message(
            msg_id=f"router-{ts_minute}-{slug}-{pr}",
            sender="router",
            intent=intent,
            repo=repo,
            pr=pr,
            branch=r.get("branch"),
            payload={
                "bucket": bucket,
                "signals": r.get("signals", {}),
                "reason": r.get("reason", ""),
            },
            ts=ts.isoformat(),
        )
        inbox = INBOX_DIR / f"{actor}.jsonl"
        with open(inbox, "a") as f:
            f.write(json.dumps(asdict(msg)) + "\n")
        routed[actor] = routed.get(actor, 0) + 1

    return {"read": len(latest), "routed": routed}


@activity.defn
async def deliver_to_inbox(result: PrStateResult) -> str:
    """Append one message to the bucket's destination inbox. Returns the path
    written. Direct synchronous routing — kept for the one-shot CLI path
    (sweep pr-state run). Prefer deposit_classified + route_classified for
    the Temporal/cron flow.
    """
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
