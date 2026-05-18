"""Bless — classifier-router for issue-comment responses.

When a maintainer responds to a comment-issue we posted (detected by leakdog's
engagement sweep), the response lands here as a card. Bless classifies
it into one of:

  - template: matched a known reply shape; canned comment used.
  - auto: novel but mechanical; LLM drafts a short reply.
  - human: needs operator judgment; routed to human-issues queue.

Template-first design (per H25, the long-term arc): as the hypothesis
graph fills with recurring reply shapes, more responses get template
matches and stop calling LLM. The actor's cost asymptotically tends to
"deterministic pattern match + file write" for the long tail of
"thanks, closing" / "you're right" / similar low-information replies.

Auto and template outputs share the same downstream: draft → comment-issue-
drafts queue → operator approves → post posts. Human outputs go to a
separate human-issues queue that the operator handles directly,
no automated reply.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from temporalio import activity
from temporalio.exceptions import ApplicationError

from sweep import observe
from sweep.types import Message, forward_ledger


BLESS_INBOX = Path.home() / ".sweep" / "inbox" / "bless.jsonl"
HUMAN_ISSUES = Path.home() / ".sweep" / "inbox" / "human-issues.jsonl"
BLESS_TEMPLATES_DIR = Path.home() / ".sweep" / "templates" / "bless"

# Default templates ship as seed — operator/retro adds more over time.
# Each is {pattern: <regex>, comment: <reply>, name: <short label>}.
# Matched against the maintainer reply text (case-insensitive).
SEED_TEMPLATES = [
    {
        "name": "thanks-closing",
        "pattern": r"\b(thanks?|thank you)\b.*\b(clos(ing|ed)|will close)\b",
        "comment": "Thanks for confirming.",
    },
    {
        "name": "youre-right",
        "pattern": r"\byou(’re|'re| are) right\b",
        "comment": "Thanks for confirming.",
    },
    {
        "name": "closed-no-comment",
        "pattern": r"^$",  # special: empty reply, matched separately
        "comment": "",  # special: no reply; bless treats as SKIP
    },
]


# ---------------------------------------------------------------- helpers

def _load_templates() -> list[dict]:
    """Load operator-curated templates from disk plus the seed set. Disk
    templates override / extend seeds. Cheap — small files, called once
    per bless_cycle."""
    tpls = list(SEED_TEMPLATES)
    if BLESS_TEMPLATES_DIR.exists():
        for p in sorted(BLESS_TEMPLATES_DIR.glob("*.json")):
            try:
                d = json.loads(p.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(d, dict) and "pattern" in d and "comment" in d:
                d.setdefault("name", p.stem)
                tpls.append(d)
    return tpls


def _match_template(reply_text: str) -> Optional[dict]:
    """Return the first matching template, or None. Templates run in
    order — seed first, then disk (sorted by filename). Operator can
    shadow a seed by naming a disk template the same."""
    if reply_text is None:
        return None
    cleaned = reply_text.strip()
    if not cleaned:
        # Empty reply (e.g. issue closed without comment) → no bless.
        return None
    for tpl in _load_templates():
        pat = tpl.get("pattern", "")
        if not pat:
            continue
        try:
            if re.search(pat, cleaned, re.IGNORECASE):
                return tpl
        except re.error:
            continue
    return None


_BLESS_FENCE = re.compile(
    r"<<<BLESS\s*(.*?)\s*COMMENT>>>",
    re.DOTALL,
)


def _parse_skill_output(stdout: str) -> Optional[dict]:
    """Pull the classification dict out of /bless's fenced output.
    Expected fields: classification (auto|human|template), and either
    comment (auto/template) or reason (human)."""
    matches = _BLESS_FENCE.findall(stdout or "")
    if not matches:
        return None
    body = matches[-1].strip()
    out: dict = {}
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip().lower()
        v = v.strip()
        out[k] = v
    if "classification" not in out:
        return None
    return out


async def _run_bless_skill(repo: str, issue: int, draft_id: str) -> tuple[str, int]:
    """Shell /bless <ref> <draft_id>. Timeout: 120s; skill reads a
    handful of GitHub fields + the comment-issue state file, drafts a reply.
    Generous enough for Sonnet variance."""
    ref = f"{repo}#{issue}"
    proc = subprocess.run(
        ["claude", "/bless", ref, draft_id],
        capture_output=True, text=True, timeout=120,
        check=False,
    )
    return proc.stdout, proc.returncode


def _deposit_tissue_draft(*, repo: str, issue: int, source_id: str,
                            comment: str, signal: str,
                            template_name: str = "") -> str:
    """Write an auto/template-classified reply into the comment-issue-drafts
    queue. Reuses the existing operator-approval surface — same `sweep
    comment-issue list` / `approve` / `discard` flow as upstream tissues."""
    from sweep.activities.comment_issue import TISSUE_DRAFTS
    ts = dt.datetime.now(dt.timezone.utc)
    draft_id = (f"bless-{repo.replace('/', '-')}-{issue}-"
                f"{ts.strftime('%Y%m%dT%H%M%S')}")
    draft = {
        "draft_id":    draft_id,
        "repo":        repo,
        "issue":       issue,
        "comment":     comment,
        "draft_chars": len(comment),
        "artifact":    "",
        "drafted_at":  ts.isoformat(),
        "source_card": f"bless:{source_id}",
        "signal":      signal,                 # "auto" | "template"
        "template":    template_name,          # "" for auto
        "from_tissue": source_id,              # the comment-issue this replies to
    }
    TISSUE_DRAFTS.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(TISSUE_DRAFTS, "a") as f:
            f.write(json.dumps(draft) + "\n")
    except OSError as e:
        observe.event("bless_draft_write_failed", repo=repo, issue=issue,
                      error_type=type(e).__name__, error=str(e)[:200])
        return ""
    return draft_id


def _deposit_human(*, repo: str, issue: int, source_id: str,
                          reason: str, reply_excerpt: str) -> str:
    """Write a human-classified reply into the human-issues
    queue. No auto-draft; the operator handles via their direct
    response surface."""
    ts = dt.datetime.now(dt.timezone.utc)
    msg_id = (f"human-{repo.replace('/', '-')}-{issue}-"
              f"{ts.strftime('%Y%m%dT%H%M%S')}")
    entry = {
        "msg_id":         msg_id,
        "repo":           repo,
        "issue":          issue,
        "ts":             ts.isoformat(),
        "reason":         reason[:300],
        "reply_excerpt":  reply_excerpt[:500],
        "from_tissue":    source_id,
        "issue_url":      f"https://github.com/{repo}/issues/{issue}",
    }
    HUMAN_ISSUES.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(HUMAN_ISSUES, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError as e:
        observe.event("bless_human_write_failed", repo=repo, issue=issue,
                      error_type=type(e).__name__, error=str(e)[:200])
        return ""
    return msg_id


# ---------------------------------------------------------------- kick

async def kick_bless_card(*, repo: str, issue: int,
                           tissue_draft_id: str,
                           reply_text: str,
                           reply_author: str,
                           comment_url: str = "",
                           incoming: Message | None = None) -> str | None:
    """Engagement detector → bless. Carries the original comment-issue draft_id
    plus the reply context inline so bless can match templates without
    a gh round-trip in the hot path."""
    from sweep.activities.pr_state import _signal_actor
    ts = dt.datetime.now(dt.timezone.utc)
    msg = Message(
        msg_id=f"bless-card-{repo.replace('/', '-')}-{issue}-"
               f"{ts.strftime('%Y%m%dT%H%M%S')}",
        sender="leakdog-engagement",
        intent="classify",
        repo=repo, pr=issue, branch=None,
        payload={
            "tissue_draft_id": tissue_draft_id,
            "reply_text":      reply_text,
            "reply_author":    reply_author,
            "comment_url":     comment_url,
        },
        ts=ts.isoformat(),
        ledger=forward_ledger(incoming),
    )
    BLESS_INBOX.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(BLESS_INBOX, "a") as f:
            f.write(json.dumps(asdict(msg)) + "\n")
    except OSError as e:
        observe.event("bless_card_write_failed", repo=repo, issue=issue,
                      error_type=type(e).__name__, error=str(e)[:200])
        return None
    observe.event("bless_card_deposited", repo=repo, issue=issue,
                  tissue_draft_id=tissue_draft_id,
                  reply_author=reply_author, msg_id=msg.msg_id)
    return await _signal_actor("bless", msg)


# ---------------------------------------------------------------- activity

@activity.defn
async def bless_cycle(msg: Message) -> dict:
    """One classify-and-route pass on one maintainer reply.

    Emits exactly one terminal event:
      - bless_routed (kind=template|auto|human) — card routed to the
        appropriate downstream (comment-issue-drafts or human-issues)
      - bless_skipped (reason) — nothing to do (empty reply, missing
        payload, dedupe)
    """
    if not msg.repo or not msg.pr:
        raise ApplicationError("bless: repo + issue required",
                               non_retryable=True)
    repo, issue = msg.repo, int(msg.pr)
    payload = msg.payload or {}
    reply_text = payload.get("reply_text", "") or ""
    tissue_draft_id = payload.get("tissue_draft_id", "")
    reply_author = payload.get("reply_author", "")

    if not reply_text.strip():
        observe.event("bless_skipped", repo=repo, issue=issue,
                      reason="empty_reply", tissue_draft_id=tissue_draft_id)
        return {"skipped": "empty_reply"}

    from sweep import budget as _budget
    _budget.record_subprocess_estimate("triage")  # similar cost class

    # Template-first: deterministic match, no LLM.
    tpl = _match_template(reply_text)
    if tpl is not None and tpl.get("comment"):
        draft_id = _deposit_tissue_draft(
            repo=repo, issue=issue, source_id=tissue_draft_id,
            comment=tpl["comment"], signal="template",
            template_name=tpl.get("name", ""),
        )
        observe.event("bless_routed", repo=repo, issue=issue,
                      kind="template", template=tpl.get("name", ""),
                      draft_id=draft_id,
                      tissue_draft_id=tissue_draft_id,
                      reply_author=reply_author)
        return {"routed": "template", "draft_id": draft_id,
                "template": tpl.get("name", "")}

    # Bootstrap stance: with no template match, default to human.
    # The LLM classifier (next branch below) stays off until we have
    # enough operator-decision data for /retro to seed templates from.
    # Per [[feedback-retro-compression-loop]]: don't add an LLM call
    # before the compression target exists. Flip via
    # `~/.sweep/control/bless_llm_enabled` once a template catalog is
    # established and the operator is comfortable with the classifier
    # gradient.
    llm_enabled = (Path.home() / ".sweep" / "control" / "bless_llm_enabled").exists()
    if not llm_enabled:
        msg_id = _deposit_human(
            repo=repo, issue=issue, source_id=tissue_draft_id,
            reason="no template match; LLM classifier disabled (bootstrap)",
            reply_excerpt=reply_text,
        )
        observe.event("bless_routed", repo=repo, issue=issue,
                      kind="human", human_msg_id=msg_id,
                      reason="default-to-human (LLM off)",
                      tissue_draft_id=tissue_draft_id,
                      reply_author=reply_author)
        return {"routed": "human", "human_msg_id": msg_id,
                "default": "no_llm"}

    # LLM classifier path (off by default — see above).
    try:
        stdout, rc = await _run_bless_skill(repo, issue, tissue_draft_id)
    except subprocess.TimeoutExpired:
        observe.event("bless_skipped", repo=repo, issue=issue,
                      reason="skill_timeout", tissue_draft_id=tissue_draft_id)
        return {"skipped": "skill_timeout"}
    except Exception as e:
        observe.event("bless_skipped", repo=repo, issue=issue,
                      reason=f"skill_error:{type(e).__name__}",
                      tissue_draft_id=tissue_draft_id)
        return {"skipped": f"skill_error:{e}"}

    parsed = _parse_skill_output(stdout)
    if not parsed:
        observe.event("bless_skipped", repo=repo, issue=issue,
                      reason="no_fence", tissue_draft_id=tissue_draft_id, rc=rc)
        return {"skipped": "no_fence"}

    cls = parsed.get("classification", "").lower()
    if cls == "auto" and parsed.get("comment"):
        draft_id = _deposit_tissue_draft(
            repo=repo, issue=issue, source_id=tissue_draft_id,
            comment=parsed["comment"], signal="auto",
        )
        observe.event("bless_routed", repo=repo, issue=issue,
                      kind="auto", draft_id=draft_id,
                      tissue_draft_id=tissue_draft_id,
                      reply_author=reply_author)
        return {"routed": "auto", "draft_id": draft_id}
    if cls == "human":
        msg_id = _deposit_human(
            repo=repo, issue=issue, source_id=tissue_draft_id,
            reason=parsed.get("reason", "(no reason)"),
            reply_excerpt=reply_text,
        )
        observe.event("bless_routed", repo=repo, issue=issue,
                      kind="human", human_msg_id=msg_id,
                      reason=parsed.get("reason", "")[:200],
                      tissue_draft_id=tissue_draft_id,
                      reply_author=reply_author)
        return {"routed": "human", "human_msg_id": msg_id}

    observe.event("bless_skipped", repo=repo, issue=issue,
                  reason=f"unknown_classification:{cls}",
                  tissue_draft_id=tissue_draft_id)
    return {"skipped": f"unknown_classification:{cls}"}
