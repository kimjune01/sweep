"""file-issue — sibling actor to comment-issue, for opening *fresh* issues.

Naming convention: this actor's verb is "file" (action of filing a new
issue); to disambiguate from the noun, the actor is named `file-issue`
and its activity is `file_issue_cycle`. Sibling holding bin is
`hold-issue` (see sweep/hold_issue_registry.py).

When `investigate_cycle` finds a separate bug worth reporting (not the
issue under investigation, but one discovered along the way), the
routing path deposits a card to the file-issue inbox. This module:

  1. Reads the source hypothesis-graph artifact.
  2. Runs the /file-issue skill to draft a fresh issue (title + body).
  3. Writes the draft to `~/.sweep/inbox/file-issue-drafts.jsonl`
     awaiting operator approval. The `sweep file-issue` CLI posts on
     approval.
  4. On approval (separate flow), `gh issue create` runs and the result
     gets recorded in the hold-issue holding bin.

The skill's contract: produce a fenced `<<<ISSUE_TITLE ... TITLE>>>`
+ `<<<ISSUE_BODY ... BODY>>>` pair, or `<<<ISSUE SKIP: reason ISSUE>>>`
when the artifact doesn't contain a clear separate-bug finding.

Posture: file-and-forget toward maintainer (no engagement polling),
keep-the-pointer toward substrate (holding bin preserves source hygraph
for deferred PR re-entry). See [[feedback_file_and_forget]].
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
from dataclasses import asdict
from pathlib import Path

from temporalio import activity
from temporalio.exceptions import ApplicationError

from sweep import observe
from sweep.types import Message, forward_ledger


FILE_ISSUE_DRAFTS = Path.home() / ".sweep" / "inbox" / "file-issue-drafts.jsonl"
FILE_ISSUE_INBOX = Path.home() / ".sweep" / "inbox" / "file-issue.jsonl"
HYPOTHESES_DIR = Path("/Users/junekim/Documents/sweep/repo-hypotheses")


async def kick_file_issue_card(repo: str, issue: int, *, source: str, signal: str,
                                incoming: Message | None = None) -> str | None:
    """Deposit a card to the file-issue inbox. Called from
    investigate_cycle when an artifact mentions a separate bug worth
    reporting. `signal` is whatever upstream classification triggered
    the kick (e.g. 'separate_bug_found'); `source` names the upstream stage."""
    from sweep.activities.pr_state import _signal_actor
    ts = dt.datetime.now(dt.timezone.utc)
    msg = Message(
        msg_id=f"file-issue-card-{repo.replace('/', '-')}-{issue}-{ts.strftime('%Y%m%dT%H%M%S')}",
        sender=source,
        intent="card",
        repo=repo, pr=issue, branch=None,
        payload={"signal": signal, "source": source},
        ts=ts.isoformat(),
        ledger=forward_ledger(incoming),
    )
    FILE_ISSUE_INBOX.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(FILE_ISSUE_INBOX, "a") as f:
            f.write(json.dumps(asdict(msg)) + "\n")
    except OSError as e:
        observe.event("file_issue_card_write_failed", repo=repo, issue=issue,
                      error_type=type(e).__name__, error=str(e)[:200])
        return None
    observe.event("file_issue_card_deposited", repo=repo, issue=issue,
                  source=source, signal=signal, msg_id=msg.msg_id)
    return await _signal_actor("file-issue", msg)


def _artifact_path(repo: str, issue: int) -> Path:
    return HYPOTHESES_DIR / f"{repo.replace('/', '__')}__{issue}.md"


# ---------------------------------------------------------------- parsing

_TITLE_FENCE = re.compile(r"<<<ISSUE_TITLE\s*(.*?)\s*TITLE>>>", re.DOTALL)
_BODY_FENCE = re.compile(r"<<<ISSUE_BODY\s*(.*?)\s*BODY>>>", re.DOTALL)
_SKIP_FENCE = re.compile(r"<<<ISSUE\s*SKIP:\s*(.*?)\s*ISSUE>>>", re.DOTALL)


def _parse_skill_output(stdout: str) -> tuple[str | None, str | None, str | None]:
    """Returns (title, body, skip_reason).
      - (t, b, None) — draft a new issue
      - (None, None, reason) — skill explicitly skipped
      - (None, None, None) — no fence at all, degraded mode
    """
    skip = _SKIP_FENCE.findall(stdout or "")
    if skip:
        return None, None, skip[-1].strip() or "(no reason)"
    titles = _TITLE_FENCE.findall(stdout or "")
    bodies = _BODY_FENCE.findall(stdout or "")
    if not titles or not bodies:
        return None, None, None
    return titles[-1].strip(), bodies[-1].strip(), None


# ---------------------------------------------------------------- skill run

async def _run_file_issue_skill(repo: str, issue: int) -> tuple[str, int]:
    """Shell /file-issue <repo>#<issue> via claude. Same shape as
    comment-issue's runner — including --print and the ANTHROPIC_API_KEY pop
    so calls route via OAuth/Max plan rather than API credits."""
    ref = f"{repo}#{issue}"
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    proc = subprocess.run(
        ["claude", "--print", "/file-issue", ref],
        capture_output=True, text=True, timeout=180,
        check=False, env=env,
    )
    return proc.stdout, proc.returncode


# ---------------------------------------------------------------- activity

@activity.defn
async def file_issue_cycle(msg: Message) -> dict:
    """One pass on one source investigation. Drafts a fresh issue
    (or skips). Posting happens later via `sweep file-issue approve`.

    Emits one terminal event:
      - file_issue_drafted (drafted=True) — draft landed in drafts file
      - file_issue_skipped (reason)       — policy or skill skip; no draft
    """
    if not msg.repo or not msg.pr:
        raise ApplicationError("file-issue: repo + source issue required",
                               non_retryable=True)
    repo, issue = msg.repo, int(msg.pr)

    artifact = _artifact_path(repo, issue)
    if not artifact.exists():
        observe.event("file_issue_skipped", repo=repo, issue=issue,
                      reason="artifact_missing", stage="precheck")
        return {"skipped": "artifact_missing", "stage": "precheck"}

    try:
        stdout, rc = await _run_file_issue_skill(repo, issue)
    except subprocess.TimeoutExpired:
        observe.event("file_issue_skipped", repo=repo, issue=issue,
                      reason="skill_timeout", stage="skill")
        return {"skipped": "skill_timeout", "stage": "skill"}
    except Exception as e:
        observe.event("file_issue_skipped", repo=repo, issue=issue,
                      reason=f"skill_error:{type(e).__name__}", stage="skill")
        return {"skipped": f"skill_error:{e}", "stage": "skill"}

    title, body, skip_reason = _parse_skill_output(stdout)
    if skip_reason:
        observe.event("file_issue_skipped", repo=repo, issue=issue,
                      reason=f"skill_skip:{skip_reason[:120]}", stage="skill")
        return {"skipped": "skill_skip", "skip_reason": skip_reason}
    if not title or not body:
        tail = (stdout or "")[-1500:]
        observe.event("file_issue_skipped", repo=repo, issue=issue,
                      reason="no_fence", stage="skill", rc=rc,
                      stdout_tail=tail)
        return {"skipped": "no_fence", "stage": "skill"}

    # Write the draft for operator review.
    ts = dt.datetime.now(dt.timezone.utc)
    draft_id = f"file-issue-{repo.replace('/', '-')}-{issue}-{ts.strftime('%Y%m%dT%H%M%S')}"
    draft = {
        "draft_id":             draft_id,
        "target_repo":          repo,
        "source_issue":         issue,
        "source_hygraph_path":  str(artifact),
        "source_investigation": f"{repo}#{issue}",
        "title":                title,
        "body":                 body,
        "body_chars":           len(body),
        "drafted_at":           ts.isoformat(),
    }
    FILE_ISSUE_DRAFTS.parent.mkdir(parents=True, exist_ok=True)
    with open(FILE_ISSUE_DRAFTS, "a") as f:
        f.write(json.dumps(draft) + "\n")
    observe.event("file_issue_drafted", repo=repo, issue=issue,
                  draft_id=draft_id, body_chars=len(body),
                  title=title[:140])
    return {"drafted": True, "draft_id": draft_id, "body_chars": len(body)}
