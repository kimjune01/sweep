"""Tissue — side-hatch actor for non-shipping investigations.

When `investigate_cycle` classifies an artifact as `no-fix` with concrete
provenance, the routing path deposits a card to the comment-issue inbox. This
module owns the card-processing activity (`comment_issue_cycle`) which:

  1. Reads the hypothesis-graph artifact.
  2. Runs the /comment-issue skill to draft a one-paragraph comment.
  3. Applies policy gates (kill list, AI-hostile, warm-org conflict,
     dedupe against existing maintainer-self-replies and prior tissues).
  4. Writes the draft to `~/.sweep/inbox/comment-issue-drafts.jsonl` awaiting
     operator approval. The `sweep comment-issue` CLI posts on approval.
  5. Emits flow events at each stage (`comment_issue_drafted`, `comment_issue_skipped`)
     so leakdog can balance the investigate → comment-issue → posted interface.

Drafting + posting are split intentionally — drafts are cheap to throw
away, comment tone is judgment-heavy, and one bad comment-issue burns more
reputation than a week of PRs earn. See [[H23]] for the bet and
falsifiers; see [[feedback-post-hoc-andon]] for why post-hoc operator
review is the right gate at this stage of the perturbation.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
from dataclasses import asdict
from pathlib import Path

from temporalio import activity
from temporalio.exceptions import ApplicationError

from sweep import gh_io, observe
from sweep.io_safe import atomic_write_text
from sweep.types import Message, forward_ledger


COMMENT_ISSUE_DRAFTS = Path.home() / ".sweep" / "inbox" / "comment-issue-drafts.jsonl"
COMMENT_ISSUE_INBOX = Path.home() / ".sweep" / "inbox" / "comment-issue.jsonl"
POST_INBOX = Path.home() / ".sweep" / "inbox" / "post.jsonl"
COMMENT_ISSUE_POSTED_STATE = Path.home() / ".sweep" / "state" / "comment_issue_posted.json"
HYPOTHESES_DIR = Path("/Users/junekim/Documents/sweep/repo-hypotheses")


async def kick_comment_issue_card(repo: str, issue: int, *,
                            source: str, signal: str,
                            incoming: Message | None = None) -> str | None:
    """Deposit a card to the comment-issue inbox and signal the actor. Called
    from `investigate_cycle` when an artifact classifies as no-fix with
    concrete provenance. Idempotent at the actor (msg_id dedupes).

    `signal` is the classifier verdict (e.g. "no-fix"), `source`
    identifies the upstream stage (e.g. "investigate"). Both flow into
    the `comment_issue_card_deposited` event so leakdog can balance the
    interface."""
    from sweep.activities.pr_state import _signal_actor
    ts = dt.datetime.now(dt.timezone.utc)
    msg = Message(
        msg_id=f"comment-issue-card-{repo.replace('/', '-')}-{issue}-{ts.strftime('%Y%m%dT%H%M%S')}",
        sender=source,
        intent="card",
        repo=repo, pr=issue, branch=None,
        payload={"signal": signal, "source": source},
        ts=ts.isoformat(),
        ledger=forward_ledger(incoming),
    )
    COMMENT_ISSUE_INBOX.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(COMMENT_ISSUE_INBOX, "a") as f:
            f.write(json.dumps(asdict(msg)) + "\n")
    except OSError as e:
        observe.event("comment_issue_card_write_failed", repo=repo, issue=issue,
                      error_type=type(e).__name__, error=str(e)[:200])
        return None
    observe.event("comment_issue_card_deposited", repo=repo, issue=issue,
                  source=source, signal=signal, msg_id=msg.msg_id)
    return await _signal_actor("comment-issue", msg)


def _artifact_path(repo: str, issue: int) -> Path:
    return HYPOTHESES_DIR / f"{repo.replace('/', '__')}__{issue}.md"


# ---------------------------------------------------------------- parsing

_COMMENT_FENCE = re.compile(
    r"<<<COMMENT\s*(.*?)\s*COMMENT>>>",
    re.DOTALL,
)


def _parse_skill_output(stdout: str) -> tuple[str | None, str | None]:
    """Extract the drafted comment from /comment-issue's fenced output.

    Returns `(comment, skip_reason)`:
      - `(text, None)` when the skill drafted a comment
      - `(None, reason)` when the skill returned SKIP: <reason>
      - `(None, None)` when the fence is missing — degraded mode
    """
    matches = _COMMENT_FENCE.findall(stdout or "")
    if not matches:
        return None, None
    body = matches[-1].strip()  # last fence wins if multiple
    if body.upper().startswith("SKIP:"):
        return None, body[5:].strip() or "(no reason)"
    return body, None


# ---------------------------------------------------------------- policy

def _has_prior_tissue(repo: str, issue: int) -> bool:
    """True if the drafts file already has an entry for this issue,
    or if a comment from us has been posted on the issue. Cheap dedupe
    against double-drafting on the same artifact."""
    # Check drafts file first — cheapest.
    if COMMENT_ISSUE_DRAFTS.exists():
        try:
            for line in COMMENT_ISSUE_DRAFTS.read_text().splitlines():
                if not line.strip():
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("repo") == repo and d.get("issue") == issue:
                    return True
        except OSError:
            pass
    # Check live issue for any comment by us — guards against the
    # operator approving an old draft and a new investigation
    # re-firing before the dedupe surface caught up.
    try:
        u = gh_io.api("user", ttl=86400)
        me = (u.get("login") if isinstance(u, dict) else "") or ""
    except Exception:
        me = ""
    if not me:
        return False
    try:
        comments = gh_io.api(
            f"repos/{repo}/issues/{issue}/comments",
            ttl=600,
        )
    except Exception:
        return False
    if not isinstance(comments, list):
        return False
    for c in comments:
        author = (c.get("user") or {}).get("login", "")
        if author == me:
            return True
    return False


def _policy_blocked(repo: str, issue: int) -> str | None:
    """Returns a short skip reason if posting here would be unwise,
    None if the draft may proceed. Gates intentionally identical in
    spirit to sift's `_passes_deterministic_issue` so the rep cost
    of comment-issue mirrors the rep cost of a PR."""
    # Kill list — operator-curated patterns.
    from sweep.activities.sift import _on_kill_list, _on_evicted_list
    if _on_kill_list(repo):
        return "kill_list"
    if _on_evicted_list(repo):
        return "evicted"
    # AI-policy hostile — repos that explicitly reject LLM contributions.
    # A comment-issue comment from us on a hostile repo is exactly the spam
    # they're trying to keep out, regardless of how polite the tone.
    try:
        if gh_io.repo_ai_policy(repo) == "hostile":
            return "ai_hostile"
    except Exception:
        pass
    # Dedupe — never comment-issue an issue we (or any prior comment-issue) already
    # touched.
    if _has_prior_tissue(repo, issue):
        return "already_commented"
    return None


# ---------------------------------------------------------------- skill IO

async def _run_comment_issue_skill(repo: str, issue: int) -> tuple[str, int]:
    """Shell /comment-issue <repo>#<issue> and return (stdout, returncode).
    Timeout is generous — the skill reads one artifact and drafts a
    short comment; 120s is plenty even with Sonnet latency variance.

    `--print` is load-bearing: without it, claude opens interactive
    mode on a non-TTY pipe and produces broken output (skill doesn't
    receive its expected context → outputs SKIP with garbage reason).
    Matches skill_runner.py's pattern. Also pop ANTHROPIC_API_KEY so
    the call routes via OAuth/Max plan, not API credits."""
    from sweep.claude_subprocess import env_without_api_key
    ref = f"{repo}#{issue}"
    env = env_without_api_key()
    proc = subprocess.run(
        ["claude", "--print", "/comment-issue", ref],
        capture_output=True, text=True, timeout=120,
        check=False, env=env,
    )
    return proc.stdout, proc.returncode


# ---------------------------------------------------------------- activity

@activity.defn
async def comment_issue_cycle(msg: Message) -> dict:
    """One side-hatch pass on one investigated issue. The card msg
    carries (repo, pr=issue_number) — same shape as upstream events.

    Emits exactly one terminal event:
      - comment_issue_drafted (skipped=False) — draft landed in inbox
      - comment_issue_skipped (reason) — policy or skill skip; nothing in inbox

    The operator-approval path is intentionally outside this activity:
    posting belongs to the CLI (`sweep comment-issue approve <id>`), so an
    error here can never accidentally post.
    """
    if not msg.repo or not msg.pr:
        raise ApplicationError("comment-issue: repo + issue required",
                               non_retryable=True)
    repo, issue = msg.repo, int(msg.pr)
    from sweep import budget as _budget
    _budget.record_subprocess_estimate("triage")  # similar cost class

    # Policy gate first — cheap, no LLM call needed if blocked.
    blocked = _policy_blocked(repo, issue)
    if blocked:
        observe.event("comment_issue_skipped", repo=repo, issue=issue,
                      reason=blocked, stage="policy")
        return {"skipped": blocked, "stage": "policy"}

    # Artifact must exist; if it doesn't, the routing was wrong.
    artifact = _artifact_path(repo, issue)
    if not artifact.exists():
        observe.event("comment_issue_skipped", repo=repo, issue=issue,
                      reason="artifact_missing", stage="precheck")
        return {"skipped": "artifact_missing", "stage": "precheck"}

    # Run the skill.
    try:
        stdout, rc = await _run_comment_issue_skill(repo, issue)
    except subprocess.TimeoutExpired:
        observe.event("comment_issue_skipped", repo=repo, issue=issue,
                      reason="skill_timeout", stage="skill")
        return {"skipped": "skill_timeout", "stage": "skill"}
    except Exception as e:
        observe.event("comment_issue_skipped", repo=repo, issue=issue,
                      reason=f"skill_error:{type(e).__name__}", stage="skill")
        return {"skipped": f"skill_error:{e}", "stage": "skill"}

    comment, skip_reason = _parse_skill_output(stdout)
    if skip_reason:
        observe.event("comment_issue_skipped", repo=repo, issue=issue,
                      reason=f"skill_skip:{skip_reason[:80]}", stage="skill")
        return {"skipped": "skill_skip", "skip_reason": skip_reason}
    if not comment:
        # Capture the actual stdout so we can see what shape the model
        # produced when the fence regex missed. Without this, no_fence
        # is an opaque failure mode.
        tail = (stdout or "")[-1500:]
        observe.event("comment_issue_skipped", repo=repo, issue=issue,
                      reason="no_fence", stage="skill", rc=rc,
                      stdout_tail=tail)
        return {"skipped": "no_fence", "stage": "skill"}

    # Write the draft. Caller (operator) approves via `sweep comment-issue`.
    ts = dt.datetime.now(dt.timezone.utc)
    draft_id = f"comment-issue-{repo.replace('/', '-')}-{issue}-{ts.strftime('%Y%m%dT%H%M%S')}"
    draft = {
        "draft_id":     draft_id,
        "repo":         repo,
        "issue":        issue,
        "comment":      comment,
        "draft_chars":  len(comment),
        "artifact":     str(artifact),
        "drafted_at":   ts.isoformat(),
        "source_card":  msg.msg_id,
    }
    COMMENT_ISSUE_DRAFTS.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(COMMENT_ISSUE_DRAFTS, "a") as f:
            f.write(json.dumps(draft) + "\n")
    except OSError as e:
        observe.event("comment_issue_skipped", repo=repo, issue=issue,
                      reason=f"write_failed:{e}", stage="write")
        return {"skipped": "write_failed", "error": str(e)[:200]}

    observe.event("comment_issue_drafted", repo=repo, issue=issue,
                  draft_id=draft_id, draft_chars=len(comment),
                  artifact=artifact.name)
    return {
        "draft_id":    draft_id,
        "draft_chars": len(comment),
        "stage":       "drafted",
    }


# ---------------------------------------------------------------- post
# Posting is a separate actor (`post`) — separation of concerns from
# drafting. Drafting is LLM-shaped (slow, can hallucinate). Posting is
# gh-API-shaped (fast, can rate-limit, has external side-effect).
# Different failure modes deserve different actors, different budget
# attribution, different retry semantics. The operator approval is the
# queue between them.


async def enqueue_post(draft: dict) -> str | None:
    """Operator-side: deposit a card on the post inbox carrying the
    approved draft. Called from `sweep comment-issue approve <draft_id>`.
    Signals post-actor on success; jsonl is the durable record."""
    from sweep.activities.pr_state import _signal_actor
    ts = dt.datetime.now(dt.timezone.utc)
    draft_id = draft.get("draft_id") or f"post-{ts.strftime('%Y%m%dT%H%M%S')}"
    msg = Message(
        msg_id=f"post-{draft_id}",
        sender="comment-issue-approve",
        intent="post",
        repo=draft.get("repo", ""),
        pr=int(draft.get("issue", 0)),
        branch=None,
        payload={
            "comment":   draft.get("comment", ""),
            "draft_id":  draft_id,
            "artifact":  draft.get("artifact", ""),
            "drafted_at": draft.get("drafted_at", ""),
        },
        ts=ts.isoformat(),
    )
    POST_INBOX.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(POST_INBOX, "a") as f:
            f.write(json.dumps(asdict(msg)) + "\n")
    except OSError as e:
        observe.event("post_card_write_failed",
                      draft_id=draft_id,
                      error_type=type(e).__name__, error=str(e)[:200])
        return None
    return await _signal_actor("post", msg)


POST_DISABLED_FLAG = Path.home() / ".sweep" / "control" / "post_disabled"


@activity.defn
async def post_cycle(msg: Message) -> dict:
    """Post one approved comment-issue draft to GitHub via `gh issue comment`.
    Emits exactly one terminal event:
      - comment_issue_posted (comment_url) — comment landed
      - comment_issue_post_failed (reason) — gh call failed; leakdog will
        see the unbalanced draft→post row
      - comment_issue_skipped (reason) — operator hold (post_disabled flag)
        or dry mode

    State side-effect on success: records the post into
    `comment_issue_posted.json` so the engagement detector can poll for
    maintainer reaction inside the 7-day window.
    """
    from sweep import budget as _budget, control_state
    if not msg.repo or not msg.pr:
        raise ApplicationError("post: repo + issue required",
                               non_retryable=True)
    repo, issue = msg.repo, int(msg.pr)
    comment = (msg.payload or {}).get("comment", "")
    draft_id = (msg.payload or {}).get("draft_id", msg.msg_id)
    if not comment:
        observe.event("comment_issue_post_failed", repo=repo, issue=issue,
                      draft_id=draft_id, reason="empty_comment")
        return {"skipped": "empty_comment"}
    # Post-specific kill switch: operator can hold posting without
    # blocking the rest of the pipeline. Independent of `sweep dry`
    # and `sweep pause`. Cleared by `rm ~/.sweep/control/post_disabled`.
    if POST_DISABLED_FLAG.exists():
        observe.event("comment_issue_skipped", repo=repo, issue=issue,
                      draft_id=draft_id, reason="post_disabled",
                      stage="post")
        return {"skipped": "post_disabled", "draft_id": draft_id}
    _budget.record_subprocess_estimate("respond")  # similar cost class (1 gh call)

    # Dry mode: write to a dry log instead of hitting gh. Same acked-
    # without-side-effect pattern the rest of the pipeline uses.
    if control_state.is_dry():
        dry_path = COMMENT_ISSUE_DRAFTS.parent / "comment-issue-drafts.dry.jsonl"
        with open(dry_path, "a") as f:
            f.write(json.dumps({
                "draft_id":  draft_id,
                "repo":      repo,
                "issue":     issue,
                "comment":   comment,
                "posted_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "dry":       True,
            }) + "\n")
        observe.event("dry_skip", site="post_cycle",
                      draft_id=draft_id, repo=repo, issue=issue)
        return {"posted": False, "dry": True, "draft_id": draft_id}

    # Live post.
    res = subprocess.run(
        ["gh", "issue", "comment", str(issue), "-R", repo,
         "--body", comment],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        stderr = res.stderr.strip()[:300]
        observe.event("comment_issue_post_failed", repo=repo, issue=issue,
                      draft_id=draft_id, reason="gh_error",
                      stderr=stderr)
        return {"posted": False, "error": stderr, "draft_id": draft_id}

    comment_url = res.stdout.strip()
    observe.event("comment_issue_posted", repo=repo, issue=issue,
                  draft_id=draft_id, comment_url=comment_url,
                  draft_chars=len(comment))
    # Hand state to the engagement detector.
    COMMENT_ISSUE_POSTED_STATE.parent.mkdir(parents=True, exist_ok=True)
    state: dict = {}
    if COMMENT_ISSUE_POSTED_STATE.exists():
        try:
            state = json.loads(COMMENT_ISSUE_POSTED_STATE.read_text())
        except (OSError, json.JSONDecodeError):
            state = {}
    state[draft_id] = {
        "repo":        repo,
        "issue":       issue,
        "comment_url": comment_url,
        "posted_at":   dt.datetime.now(dt.timezone.utc).isoformat(),
        "status":      "watching",
    }
    try:
        COMMENT_ISSUE_POSTED_STATE.write_text(json.dumps(state))
    except OSError:
        pass
    return {"posted": True, "comment_url": comment_url, "draft_id": draft_id}
