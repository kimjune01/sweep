"""PR-state activities — classify open authored PRs into buckets and
deliver one message per PR to the matching downstream actor's inbox.

Each activity is independently callable for development in isolation.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import asyncio
import json
import subprocess
from dataclasses import asdict
from pathlib import Path

from temporalio import activity
from temporalio.exceptions import ApplicationError

from sweep import control_state, gh_io, llm_cli, observe, retro_state
from sweep.io_safe import atomic_write_text
from sweep.types import (
    BUCKET_ROUTING,
    Message,
    PrLiveState,
    PrStateResult,
)

# actor → workflow id mapping. Add new entries here when actors get wired.
# Routing writes to inbox jsonl AND signals the matching Temporal actor.
# Missing entry → jsonl-only (legacy behavior, no actor consumes it).
# Routing table: actor name (matches inbox file basename and remit
# bucket) → temporal workflow id. SkillActor instances share a single
# workflow class — they're distinguished only by id. QaActor is its
# own class (concurrent dispatcher, different shape).
_ACTOR_WORKFLOW_IDS = {
    "qa":          "qa-actor",
    "respond":     "respond-actor",
    "triaged":     "triage-actor",
    "investigate":   "investigate-actor",
    "reinvestigate": "reinvestigate-actor",
    "reqa":          "reqa-actor",
    "attest":        "attest-actor",
    "metronome":     "metronome-actor",
    "retro":         "retro-actor",
    "sift":        "sift-actor",
    "comment-issue":      "comment-issue-actor",
    "sign":        "sign-actor",
    "post":        "post-actor",
    "immunize":    "immunize-actor",
    "bless":       "bless-actor",
    "remit":       "remit-actor",
    "submit":      "submit-actor",
    "compose":     "compose-actor",
    "rope":        "rope-actor",
    "scout":       "scout-actor",
    "amend":       "amend-actor",
    "check":       "check-actor",
    "heart":       "heart-actor",
    "ping":        "ping-actor",
    "bug-reporter": "bug-reporter-actor",
}

# View-only sinks: their inbox jsonl IS the consumer; no Temporal
# actor processes them. Routing still writes the jsonl row, but
# signaling would emit a spurious signal_failed/unwired_actor — these
# are not unwired, they're intentionally signal-less. retro is the
# wait-bucket audit trail; human is the operator inbox (you are the
# consumer, surfaced via cockpit's 📥 chip and `sweep inbox actor human`).
_VIEW_ONLY_ACTORS: set[str] = {"human", "retro_audit"}


async def _signal_actor(actor: str, msg: "Message") -> str | None:
    """Best-effort signal: tell the Temporal actor it has a new message.
    Returns the workflow id on success, None if the actor isn't wired or
    temporal is unreachable. Returns None rather than raising so the jsonl
    write (the source of truth) stays atomic with the deposit; visibility
    comes via `signal_failed` events so silent stalls don't hide.
    """
    if actor in _VIEW_ONLY_ACTORS:
        return None
    wf_id = _ACTOR_WORKFLOW_IDS.get(actor)
    if not wf_id:
        observe.event("signal_failed", actor=actor, msg_id=msg.msg_id,
                      reason="unwired_actor")
        return None
    try:
        from temporalio.client import Client
        from sweep.system import TEMPORAL_ADDR
        from sweep.workflows.qa_actor import QaActor
        from sweep.workflows.skill_actor import SkillActor

        client = await Client.connect(TEMPORAL_ADDR)
        handle = client.get_workflow_handle(wf_id)
        # QaActor and SkillActor both expose a `deliver` signal taking
        # a Message. Pick the right class for typed signaling.
        deliver = QaActor.deliver if actor == "qa" else SkillActor.deliver
        await handle.signal(deliver, msg)
        return wf_id
    except Exception as e:
        observe.event("signal_failed", actor=actor, msg_id=msg.msg_id,
                      wf_id=wf_id, error_type=type(e).__name__,
                      error=str(e)[:300])
        return None

INBOX_DIR = Path.home() / ".sweep" / "inbox"
CLASSIFIED_INBOX = INBOX_DIR / "classified.jsonl"
# Terminal-state sink: every PR that classifies to `done` (approved,
# closed, or merged) gets appended here, plus manual entries (drafts
# the operator parked, etc.). Append-only durable artifact so the
# operator can see "these are out of rotation" without grepping event
# logs. Dedup on read by (repo, pr); latest row wins. Named `sink.jsonl`
# rather than `done.jsonl` because the destination is the artifact, not
# the bucket label.
SINK = INBOX_DIR / "sink.jsonl"


def _sink_pr(repo: str, pr: int, reason: str, state: str = "") -> None:
    """Append one terminal-state row to the done sink. Best-effort —
    a sink write failure must not break routing, so we swallow."""
    try:
        SINK.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
            "repo": repo,
            "pr": pr,
            "reason": reason,
            "state": state,
        }
        with open(SINK, "a") as f:
            f.write(json.dumps(row) + "\n")
    except Exception as e:
        observe.event("sink_write_failed", repo=repo, pr=pr,
                      error_type=type(e).__name__, error=str(e)[:200])


# ------------------------------------------------------------ gh wrappers


@activity.defn
async def gh_search_open_authored(limit: int = 50) -> list[dict]:
    """List my open PRs across GitHub. Returns minimal fields; callers fetch
    detail per PR via gh_pr_view."""
    from sweep import budget
    budget.set_caller("remit")
    # Use gh_io.api with a 24h cache instead of a fresh subprocess —
    # identity doesn't change in practice. Same TTL the rest of the
    # codebase uses for `gh api user`. Saves ~1 call per workflow tick.
    from sweep.cache_policy import IDENTITY_TTL
    u = gh_io.api("user", ttl=IDENTITY_TTL)
    user = (u.get("login") if isinstance(u, dict) else "") or ""
    if not user:
        return []
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
    from sweep import budget
    budget.set_caller("remit")
    try:
        from sweep.cache_policy import PR_STATE_TTL
        data = gh_io.pr_view(repo, pr, ttl=PR_STATE_TTL)
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
    # (not exposed via `gh pr view --json`). Lazy-fetch: only when the
    # PR plausibly needs human attention — CHANGES_REQUESTED or maintainer
    # has commented. For wait/done/qa-mechanical PRs (~90% of the queue),
    # the inline comments don't influence the classification, so we
    # skip the call entirely. Halves the per-PR fetch cost in steady
    # state.
    needs_inline = (
        data.get("reviewDecision") == "CHANGES_REQUESTED"
        or bool(data.get("comments"))
    )
    if needs_inline:
        try:
            data["_inline_comments"] = gh_io.pr_inline_comments(repo, pr)
        except Exception as e:
            observe.event("inline_comments_failed", repo=repo, pr=pr,
                          error_type=type(e).__name__, error=str(e)[:200])
            data["_inline_comments"] = []
    else:
        data["_inline_comments"] = []

    # CI derivation. Rollup entries come in two shapes:
    #   CheckRun       — has `conclusion` (SUCCESS/FAILURE/...) and `name`
    #   StatusContext  — has `state` (SUCCESS/FAILURE/PENDING/ERROR) and
    #                    `context` (no `name`, no `conclusion`)
    # Buildkite, CircleCI, etc. emit StatusContext — the old picker
    # missed them entirely. Treat both shapes uniformly. When multiple
    # checks fail, prefer a non-CLA-class failure: a real CI break is
    # higher-priority than a CLA bot the sign-actor can mechanically
    # retry. Picking the first FAILURE in rollup order silently routed
    # PRs with both kinds to `sign` (CLA-class bucket wins below) and
    # the real build failure was lost.
    def _entry_failed(c: dict) -> bool:
        return (c.get("conclusion") == "FAILURE"
                or c.get("state") in ("FAILURE", "ERROR"))

    def _entry_name(c: dict) -> str:
        return c.get("name") or c.get("context") or ""

    rollup = data.get("statusCheckRollup") or []
    failures = [_entry_name(c) for c in rollup if _entry_failed(c)]
    failing = next((n for n in failures if not _is_cla_class_check(n)),
                   failures[0] if failures else "")
    def _entry_terminal(c: dict) -> bool:
        # CheckRun is terminal once status == "COMPLETED"; StatusContext
        # is terminal once state is SUCCESS/FAILURE/ERROR (PENDING is
        # the only non-terminal state).
        if "conclusion" in c or "status" in c:
            return c.get("status") == "COMPLETED"
        return c.get("state") in ("SUCCESS", "FAILURE", "ERROR")

    def _entry_succeeded(c: dict) -> bool:
        return (c.get("conclusion") == "SUCCESS"
                or c.get("state") == "SUCCESS")

    if failing:
        ci = "failing"
    elif rollup and any(not _entry_terminal(c) for c in rollup):
        ci = "pending"
    elif rollup and all(_entry_succeeded(c) for c in rollup):
        ci = "green"
    else:
        ci = "unknown"

    # activity_h
    updated = dt.datetime.fromisoformat(data["updatedAt"].replace("Z", "+00:00"))
    now = dt.datetime.now(dt.timezone.utc)
    activity_h = (now - updated).total_seconds() / 3600.0

    # Unified PR-thread classification — one sonnet call covers both
    # "maintainer asked unanswered question" and "maintainer raised
    # unaddressed concern", instead of two Opus calls (and a nested
    # third for the substantive-reply judge). CodeRabbit findings count
    # as non-author concerns; the LLM judges substance, not source.
    comments = data.get("comments") or []
    author_login = (data.get("author") or {}).get("login", "")
    thread_verdict = await _classify_pr_thread(
        comments, author_login=author_login, repo=repo, pr=pr,
    )
    maintainer_question = thread_verdict["question_unaddressed"]
    maintainer_raised_concern = thread_verdict["concern_unaddressed"]

    member_approved_over_cr = _member_approved_over_cr(
        data.get("reviews") or [], author_login=author_login,
    )
    has_non_author_lgtm = any(
        (r.get("state") or "").upper() == "APPROVED"
        and (r.get("author") or {}).get("login", "") != author_login
        for r in (data.get("reviews") or [])
    )

    return PrLiveState(
        repo=repo,
        pr=pr,
        branch=data.get("headRefName", ""),
        title=data.get("title", ""),
        url=data.get("url", ""),
        state=(data.get("state") or "").upper(),
        review_decision=data.get("reviewDecision") or "",
        mergeable=data.get("mergeable") or "",
        ci=ci,
        activity_h=activity_h,
        maintainer_question=maintainer_question,
        is_draft=bool(data.get("isDraft")),
        failing_check=failing,
        maintainer_raised_concern=maintainer_raised_concern,
        member_approved_over_cr=member_approved_over_cr,
        has_non_author_lgtm=has_non_author_lgtm,
    )


def _member_approved_over_cr(reviews: list[dict], *, author_login: str) -> bool:
    """True iff a MEMBER/OWNER submitted APPROVED *after* the latest
    non-author CHANGES_REQUESTED. GH's `reviewDecision` aggregate doesn't
    auto-dismiss the earlier CR, so the classifier needs this side-channel.

    Self-reviews are ignored on both sides — the author can't approve
    over their own review, and a CR from the author isn't blocking.
    """
    cr_ts = ""
    approve_ts = ""
    for r in reviews:
        login = (r.get("author") or {}).get("login") or ""
        if login == author_login:
            continue
        state = (r.get("state") or "").upper()
        assoc = (r.get("authorAssociation") or "").upper()
        ts = r.get("submittedAt") or ""
        if state == "CHANGES_REQUESTED" and ts > cr_ts:
            cr_ts = ts
        elif state == "APPROVED" and assoc in ("MEMBER", "OWNER") and ts > approve_ts:
            approve_ts = ts
    return bool(approve_ts) and (not cr_ts or approve_ts > cr_ts)


_THREAD_CLASSIFIER_SYSTEM = (
    "You read a GitHub PR comment thread and emit a JSON verdict on two "
    "conditions. The PR has one author; everyone else is a non-author "
    "(maintainer, collaborator, or a code-review bot like CodeRabbit — "
    "bot findings count exactly like human ones; judge the substance, "
    "not the source).\n\n"
    "Output ONLY this JSON, no prose, no markdown fences:\n"
    '  {\"concern_unaddressed\": <bool>, \"question_unaddressed\": <bool>}\n\n'
    "concern_unaddressed=true iff a non-author raised a NEW bug, missing "
    "case, broken scenario, or technical gap that the author has NOT "
    "substantively addressed in a later reply. Approvals, style nits, "
    "off-topic chatter, and 'lgtm' are not concerns.\n\n"
    "question_unaddressed=true iff a non-author asked a direct question "
    "and the author has NOT substantively answered. Short acks ('thanks', "
    "'will do', 'looking into it') do NOT count as answers; a direct "
    "explanation or fix DOES count.\n\n"
    "If the author's most recent message is after the non-author's "
    "concern/question AND directly addresses it, both flags should be "
    "false. If the thread is empty or unparseable, return both false. "
    "On a true ambiguity, prefer true on question_unaddressed (cheap to "
    "land in human bucket) and false on concern_unaddressed (re-investigate "
    "is expensive)."
)


async def _classify_pr_thread(
    comments: list[dict],
    *,
    author_login: str,
    repo: str,
    pr: int,
) -> dict:
    """One sonnet call. Returns {concern_unaddressed, question_unaddressed}.

    Replaces three older Opus-bound judges (_open_maintainer_question,
    _open_maintainer_concern, _author_addressed). Cheap pre-filter:
    if no non-author comments exist, skip the LLM entirely.
    """
    candidates = [
        c for c in comments
        if (c.get("author") or {}).get("login") != author_login
        and (c.get("body") or "").strip()
    ]
    if not candidates:
        return {"concern_unaddressed": False, "question_unaddressed": False}

    lines: list[str] = []
    for c in comments:
        body = (c.get("body") or "").strip()
        if not body:
            continue
        login = (c.get("author") or {}).get("login", "?")
        assoc = c.get("authorAssociation") or ""
        ts = c.get("createdAt", "")
        role = "AUTHOR" if login == author_login else f"NON-AUTHOR[{login},{assoc}]"
        lines.append(f"[{ts}] {role}:\n{body[:1500]}")
    thread = "\n\n".join(lines)[:8000]

    user = f"Author login: {author_login}\n\nThread:\n{thread}"
    try:
        out = await asyncio.to_thread(
            llm_cli.call, _THREAD_CLASSIFIER_SYSTEM, user,
            timeout_s=60, model="sonnet",
        )
        parsed = json.loads((out or "").strip())
        return {
            "concern_unaddressed": bool(parsed.get("concern_unaddressed")),
            "question_unaddressed": bool(parsed.get("question_unaddressed")),
        }
    except Exception as e:
        observe.event("llm_judge_failed", site="classify_pr_thread",
                      repo=repo, pr=pr,
                      error_type=type(e).__name__, error=str(e)[:300])
        # Asymmetric fallback matches the prior defaults: question
        # defaults true (cheap human-bucket landing), concern defaults
        # false (re-investigate is costly to fire spuriously).
        return {"concern_unaddressed": False, "question_unaddressed": True}


# ------------------------------------------------------------ classifier


# Check-name patterns the qa actor can plausibly auto-fix. Case-insensitive
# substring match. Add patterns as the qa actor's repertoire grows; treat
# unknown patterns as "investigate" — better to surface for a human than
# have qa loop on something it'll never fix.
_MECHANICAL_CHECK_PATTERNS = (
    "changelog",
    "lint",
    "format",
    "rustfmt",
    "gofmt",
    "prettier",
    "black",
    "ruff",
    "pre-commit",
    "commitlint",
    "spelling",
    "typo",
    # Intentionally NOT here: dco, sign-off, license/cla. Those require
    # the human's actual signature or legal agreement — qa can't fake
    # one. They flow to human-bucket via the maintainer-question path or
    # sit as "investigate" if CI surfaces them without a maintainer
    # comment.
)


def _is_mechanical_check(check_name: str) -> bool:
    if not check_name:
        return False
    n = check_name.lower()
    return any(pat in n for pat in _MECHANICAL_CHECK_PATTERNS)


_CLA_CLASS_PATTERNS = ("cla", "license/cla", "dco", "developer certificate",
                       "contributor license", "sign-off")


def _is_cla_class_check(check_name: str) -> bool:
    """True when the failing check is a CLA-class signing requirement
    that the sign-actor can address by posting the bot's magic phrase.
    Matches on check name substring (case-insensitive)."""
    if not check_name:
        return False
    n = check_name.lower()
    return any(pat in n for pat in _CLA_CLASS_PATTERNS)


def _msg_id(repo: str, pr: int, bucket: str) -> str:
    """Deterministic id from (repo, pr, bucket). Stable across retries —
    earlier call-time-minute formulation produced different ids on
    Temporal-driven retries, defeating actor inbox dedup."""
    slug = repo.replace("/", "-")
    digest = hashlib.sha256(f"{repo}-{pr}-{bucket}".encode()).hexdigest()[:8]
    return f"prstate-{slug}-{pr}-{bucket}-{digest}"


@activity.defn
async def classify_one_pr(state: PrLiveState) -> PrStateResult:
    """Pure-ish classifier: bucket rules applied in priority order."""
    rd = state.review_decision
    ci = state.ci
    merge = state.mergeable
    reasons: list[str] = []

    # A MEMBER/OWNER approving over a stale collaborator CHANGES_REQUESTED
    # leaves GH's aggregate pinned to CHANGES_REQUESTED until the earlier
    # review is dismissed. Treat the member approval as effective for the
    # subsequent rules so the PR can reach `done` (or fall through to the
    # CI-failing branches and trigger a re-attest) instead of being held
    # in `human` indefinitely. wild-linker/wild#1924 was the witness.
    if state.member_approved_over_cr and rd == "CHANGES_REQUESTED":
        reasons.append("member APPROVED over outstanding CR — effective approval")
        rd = "APPROVED"

    # 0. terminal state — CLOSED / MERGED PRs short-circuit to done.
    #    Routing them into reqa / reinvestigate burns a worktree clone
    #    for a branch the head fork has already deleted (typical
    #    post-close cleanup); the andon that fires is misleading
    #    because the bug is "we shouldn't be looking at this PR" not
    #    "the worktree is broken." Empty branch is also terminal —
    #    gh returns "" for headRefName on detached PRs.
    if state.state and state.state != "OPEN":
        return PrStateResult(
            repo=state.repo,
            pr=state.pr,
            branch=state.branch,
            bucket="done",
            reason=f"PR state={state.state} — terminal, out of rotation",
            signals={"state": state.state},
        )

    # 1. close (terminal — needs explicit signal, not stale-age)
    #    We only auto-flag close for: changes_requested + close-this-PR-language.
    #    Superseded-PR detection lives elsewhere; not enough signal here yet.
    #    So close is rarely chosen — that's per the user's "never recommend
    #    closing a stale PR" rule.

    # 2a. reinvestigate — maintainer raised a new bug/concern in-PR that
    # the author hasn't addressed. Routes to the engagement-lane
    # reinvestigate-actor (NOT production investigate), so reqa →
    # respond runs without the new-PR-shaped compose+submit gates.
    # Takes priority over human-bucket so concern+question on the
    # same PR routes here.
    if state.maintainer_raised_concern:
        bucket = "reinvestigate"
        reasons.append("maintainer raised new concern in-PR")
    # 2b. reinvestigate — CHANGES_REQUESTED or maintainer_question on a
    # PR whose CI isn't visibly green. Covers failing CI (test broken)
    # AND unknown CI (draft, never-ran, rollup-empty — wild #1924's
    # case after we drafted it for org-cap cleanup) AND pending CI
    # (substrate runs in container anyway, no reason to wait). The
    # substrate can re-attest in either case; the maintainer's "have
    # you tested?" / "this is broken" gets answered structurally with
    # a fresh receipt. Only after the substrate has tried (and either
    # passes the gate or surfaces what's still broken) does a failure
    # to attest punt to operator inbox via [[O9]]. Supersedes the
    # previous "any CR → human" rule which dumped wild #1924 into the
    # operator's lap without trying.
    elif (rd == "CHANGES_REQUESTED" or state.maintainer_question) and ci != "green":
        bucket = "reinvestigate"
        reasons.append(
            f"CR+ci={ci} ({state.failing_check or 'no-failing-check'}) — substrate re-attests"
        )
    # 2c. human — CR or maintainer_question on a green PR. CI is
    # already green, so there's nothing to fix structurally; the
    # ask is for discussion or interpretation. Operator handles.
    elif rd == "CHANGES_REQUESTED" or state.maintainer_question:
        bucket = "human"
        reasons.append(
            "changes_requested" if rd == "CHANGES_REQUESTED" else "maintainer asked"
        )
    # 3. rebase
    elif merge == "CONFLICTING":
        bucket = "rebase"
        reasons.append("merge conflicts")
    # 4. reqa vs reinvestigate vs sign — split CI failures by check kind.
    # CLA-class failures (cla-assistant, license check, dco) route to
    # sign-actor which posts the bot's magic-phrase comment + recheck.
    # The operator's policy is blanket: copyright released, sign the
    # CLA. Encoded here so the substrate doesn't burn a /investigate
    # cycle on a non-investigation problem. mechanical checks (lint,
    # format) go to reqa; everything else needing code-read goes to
    # reinvestigate.
    elif ci == "failing":
        if _is_cla_class_check(state.failing_check):
            bucket = "sign"
            reasons.append(f"CLA-class failing check: {state.failing_check or 'unspecified'}")
        elif _is_mechanical_check(state.failing_check):
            bucket = "reqa"
            reasons.append(f"CI failure: {state.failing_check or 'unspecified'}")
        else:
            bucket = "reinvestigate"
            reasons.append(f"CI failure (non-mechanical): {state.failing_check or 'unspecified'}")
    # 5. done — PR is in the maintainer's court. We don't merge; that's
    # their job. No actor, no audit — out of our rotation until the
    # maintainer's action fires a notification.
    #
    # Two shapes count as done:
    #   (a) formal rd=APPROVED — gh aggregate says someone with merge
    #       rights approved.
    #   (b) any non-author LGTM + green + mergeable — covers the case
    #       where NONE/CONTRIBUTOR reviewers approved but the maintainer
    #       hasn't formally reviewed yet. Operator has nothing to do
    #       except wait. Witness: feldera/feldera#6219 (2 NONE-assoc
    #       APPROVEDs, MEMBER silent for 4 days, was landing in human).
    elif merge == "MERGEABLE" and ci == "green" and (
        rd == "APPROVED" or state.has_non_author_lgtm
    ):
        bucket = "done"
        if rd == "APPROVED":
            reasons.append("approved + mergeable + green CI — maintainer's court")
        else:
            reasons.append(
                "non-author LGTM + mergeable + green CI — waiting on maintainer review"
            )
    # 6. wait (default) — no action signal yet, but keep watching.
    # Wait is an action: routes to retro for periodic audit.
    else:
        bucket = "wait"
        reasons.append("no action signal")

    observe.incr(f"remit_bucket:{bucket}")
    # Log the classification as an event so retro can read the
    # distribution and pattern-match misclassifications. Counters tell
    # us "n PRs went to bucket X"; the event stream tells us "this
    # specific PR went to X with reason Y on these signals" — that's
    # the level retro needs to spot drift (qa actor looping on the
    # same check, classifier flipping a PR between buckets, etc.).
    observe.event(
        "remit_classified",
        repo=state.repo,
        pr=state.pr,
        bucket=bucket,
        reason="; ".join(reasons),
        review=rd,
        ci=ci,
        mergeable=merge,
        failing_check=state.failing_check,
        maintainer_question=state.maintainer_question,
    )
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
        is_draft=state.is_draft,
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
        "is_draft": result.is_draft,
    }
    CLASSIFIED_INBOX.parent.mkdir(parents=True, exist_ok=True)
    with open(CLASSIFIED_INBOX, "a") as f:
        f.write(json.dumps(record) + "\n")
    return str(CLASSIFIED_INBOX)


@activity.defn
async def route_classified() -> dict:
    """Read classified.jsonl, route each PR to its bucket's inbox.

    Runs on its own takt — cheap, rule-based, can re-run if routing logic
    changes. Idempotent per (repo, pr, classification_ts): two cron firings
    over the same classified.jsonl produce the same msg_ids, and downstream
    inbox readers dedup on msg_id.
    """
    if retro_state.is_halted():
        # Backpressure: don't move classified records into actor inboxes
        # while the human owes Attend on pending SOAP one-pagers.
        observe.incr("halted_skip:route")
        return {"read": 0, "routed": {}, "skipped_acked": 0, "halted": True}
    if control_state.is_paused():
        observe.incr("paused_skip:route")
        return {"read": 0, "routed": {}, "skipped_acked": 0,
                "halted": False, "paused": True}
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
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
    for (repo, pr), r in latest.items():
        bucket = r.get("bucket", "wait")
        # "done" is genuinely no-action — maintainer's court, we don't
        # merge. Ack, observe, drop. Distinct from "wait" which still
        # routes to retro for audit.
        if bucket == "done":
            observe.event("remit_done", repo=repo, pr=pr,
                          reason=r.get("reason", ""))
            _sink_pr(repo, pr, r.get("reason", ""),
                       state=str(r.get("signals", {}).get("state", "")))
            routed["done"] = routed.get("done", 0) + 1
            continue
        actor, intent = BUCKET_ROUTING.get(bucket, ("retro", "audit"))
        # Stable msg_id per (repo, pr, bucket) — NO timestamp. Without
        # this, every cron firing of route_classified for the same PR
        # mints a fresh id and the actor inbox accumulates duplicates
        # (was 142 rows for one PR in retro before we noticed). The
        # bucket is part of the key so bucket transitions get their own
        # id, and downstream inbox_states dedupe naturally collapses
        # repeated re-routes into one entry.
        slug = repo.replace("/", "-")
        msg = Message(
            msg_id=f"router-{slug}-{pr}-{bucket}",
            sender="router",
            intent=intent,
            repo=repo,
            pr=pr,
            branch=r.get("branch"),
            payload={
                "bucket": bucket,
                "signals": r.get("signals", {}),
                "reason": r.get("reason", ""),
                "is_draft": bool(r.get("is_draft", False)),
            },
            ts=now_iso,
        )
        # Dry mode is NOT checked here. Dry means "no new public
        # commitments" — once a PR is out there, the maintainer is on
        # real-world time and we owe them a response regardless of
        # operator pause/dry state. The only actor that gates on dry is
        # submit-actor (new-PR-create), enforced at pause_gate.should_idle.
        inbox = INBOX_DIR / f"{actor}.jsonl"
        with open(inbox, "a") as f:
            f.write(json.dumps(asdict(msg)) + "\n")
        # Best-effort actor signal — qa actor receives messages this way;
        # buckets without a wired actor just stay in the jsonl view layer.
        await _signal_actor(actor, msg)
        routed[actor] = routed.get(actor, 0) + 1

    return {"read": len(latest), "routed": routed, "skipped_acked": 0}


@activity.defn
async def deliver_to_inbox(result: PrStateResult) -> str:
    """Append one message to the bucket's destination inbox. Returns the path
    written. Direct synchronous routing — kept for the one-shot CLI path
    (legacy). Prefer deposit_classified + route_classified for
    the Temporal/cron flow.
    """
    if result.bucket == "done":
        observe.event("remit_done", repo=result.repo, pr=result.pr,
                      reason=result.reason)
        _sink_pr(result.repo, result.pr, result.reason,
                   state=str(result.signals.get("state", "")))
        return f"(sink — {result.reason})"
    actor, intent = BUCKET_ROUTING[result.bucket]
    ts = dt.datetime.now(dt.timezone.utc)

    msg = Message(
        msg_id=_msg_id(result.repo, result.pr, result.bucket),
        sender="remit",
        intent=intent,
        repo=result.repo,
        pr=result.pr,
        branch=result.branch,
        payload={
            "bucket": result.bucket,
            "signals": result.signals,
            "reason": result.reason,
            "is_draft": result.is_draft,
        },
        ts=ts.isoformat(),
    )

    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    line = json.dumps(asdict(msg)) + "\n"
    # Dry mode is NOT checked here. Dry means "no new public
    # commitments" — only submit-actor gates on it (at pause_gate). Once
    # a PR exists, the maintainer is on real-world time and we owe them
    # a response regardless of operator pause/dry state.
    inbox = INBOX_DIR / f"{actor}.jsonl"
    # Append-only — read all lines later, dedupe by msg_id.
    with open(inbox, "a") as f:
        f.write(line)
    # Best-effort actor signal; silent when actor isn't wired (drip, retro).
    await _signal_actor(actor, msg)
    return str(inbox)
