"""sign — handles CLA-class signing autonomously when the bot template
is known.

Witness: 2026-05-18, MaterializeInc/materialize#36491. CLA Assistant
Lite posts a comment with a magic phrase the operator must echo. The
operator's policy is blanket: copyright released, sign the CLA. So the
signing is deterministic work, not judgment work — encode it.

Preconditions checked per card:
  1. PR has a failing CLA-class check (cla-assistant, cla-bot, etc.).
     If not, drop the card silently — no work to do.
  2. The bot comment uses a recognized template the actor knows how to
     respond to. If not, escalate to human inbox with the bot's text
     so the operator can sign manually or extend the actor.
  3. post_disabled flag is off (same gate as ping / post / comment-issue).

Upstreams (cards arrive here from):
  - remit: classifies a PR with cla-class failing check → "sign" bucket
  - submit (deferred): after a successful publish, if the new PR shows
    a CLA check, kick sign so the freshly-shipped PR gets signed
    without an extra remit round-trip

Downstream: on success, emits `sign_done` and lets the next state-cycle
(notification-poller → remit) re-classify the now-unblocked PR. On
"unknown bot" or "sign failed," kicks the human inbox.

Known CLA bot templates:

  CLA Assistant Lite: bot comment contains the magic phrase template
    "I have read the Contributor License Agreement (CLA) and I hereby
    sign the CLA." Operator posts that exact line, then `recheck`.

Unknown templates today (will escalate to human): EasyCLA, Salesforce
CLA, github-app-based CLA bots that require web UI signing. Add cases
as you encounter them.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import time
from dataclasses import asdict
from pathlib import Path

from temporalio import activity
from temporalio.exceptions import ApplicationError

from sweep import observe
from sweep.types import Message, forward_ledger


SIGN_INBOX = Path.home() / ".sweep" / "inbox" / "sign.jsonl"
POST_DISABLED_FLAG = Path.home() / ".sweep" / "control" / "post_disabled"

_SHIM_SYSTEM = (
    "You are a structured-output parser for CLA/DCO signing procedures. "
    "You receive a CLA-class bot's comment text (and possibly some "
    "context about recent commits) and decide what action signs it. "
    "Procedures vary by repo: CLA Assistant Lite wants an exact-phrase "
    "comment; DCO wants `Signed-off-by:` lines in commits; EasyCLA "
    "wants a web-UI click; some require posting a magic word like "
    "`recheck`.\n\n"
    "Output JSON only (no prose, no markdown fences) matching:\n"
    "{\n"
    '  "action": "post-comment" | "signoff-commits" | "web-ui" | "unknown",\n'
    '  "comment_text": str,        // exact text to post (action=post-comment); empty otherwise\n'
    '  "recheck_text": str,        // comment to trigger re-check after action; empty if none needed\n'
    '  "rationale": str            // one short sentence on why this is the right action\n'
    "}\n\n"
    "Rules:\n"
    "- `post-comment`: use when the bot explicitly says to post a "
    "  specific phrase or invitation to sign by commenting. comment_text "
    "  must be the EXACT phrase verbatim, no paraphrasing.\n"
    "- `signoff-commits`: DCO bots checking for `Signed-off-by:` lines. "
    "  The actor cannot rewrite history autonomously; this action means "
    "  'human-required, post a comment explaining what they need to do.'\n"
    "- `web-ui`: bot links to a website to click through (EasyCLA, "
    "  cla-assistant.io). Actor cannot drive a browser flow autonomously; "
    "  same as signoff-commits in routing — human-required.\n"
    "- `unknown`: bot comment doesn't reveal the procedure. Andon.\n"
)


@activity.defn
async def kick_sign_card(repo: str, pr: int,
                         sender: str = "remit",
                         incoming: Message | None = None) -> str | None:
    """Deposit a sign card on sign.jsonl and signal sign-actor."""
    from sweep.activities.pr_state import _signal_actor
    ts = dt.datetime.now(dt.timezone.utc)
    slug = repo.replace("/", "-")
    msg_id = f"sign-{slug}-{pr}"
    msg = Message(
        msg_id=msg_id,
        sender=sender,
        intent="sign-cla",
        repo=repo,
        pr=pr,
        branch=None,
        payload={},
        ts=ts.isoformat(),
        ledger=forward_ledger(incoming),
    )
    SIGN_INBOX.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(SIGN_INBOX, "a") as f:
            f.write(json.dumps(asdict(msg)) + "\n")
    except OSError as e:
        observe.event("sign_card_write_failed", repo=repo, pr=pr,
                      error_type=type(e).__name__, error=str(e)[:200])
        return None
    return await _signal_actor("sign", msg)


def _failing_cla_check(repo: str, pr: int) -> dict | None:
    """Return the failing CLA-class check run if present, else None.
    Matches on workflow/check name containing 'cla' (case-insensitive).
    The precondition: we only sign when there's actually a CLA check
    failing — don't post on PRs that don't need it."""
    try:
        r = subprocess.run(
            ["gh", "pr", "view", str(pr), "--repo", repo,
             "--json", "statusCheckRollup"],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode != 0:
            return None
        data = json.loads(r.stdout or "{}")
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return None
    for c in data.get("statusCheckRollup") or []:
        name = (c.get("name") or c.get("context") or "").lower()
        if "cla" not in name and "license" not in name:
            continue
        if c.get("conclusion") in ("FAILURE", "FAILED", "ACTION_REQUIRED"):
            return c
    return None


def _fetch_bot_comment(repo: str, pr: int) -> str:
    """Return the most recent CLA-class bot comment body. Empty string
    if none found."""
    try:
        r = subprocess.run(
            ["gh", "api", f"repos/{repo}/issues/{pr}/comments",
             "--paginate"],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode != 0:
            return ""
        comments = json.loads(r.stdout or "[]")
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return ""
    last = ""
    for c in comments:
        body = c.get("body") or ""
        login = ((c.get("user") or {}).get("login") or "").lower()
        is_bot_ish = "bot" in login or "cla" in body.lower() or "dco" in body.lower()
        if not is_bot_ish:
            continue
        if any(k in body.lower() for k in
               ("cla", "contributor license", "dco",
                "developer certificate", "sign-off", "signoff")):
            last = body
    return last


async def _ask_shim(bot_comment: str, repo: str, pr: int) -> dict:
    """Sonnet shim: bot comment in, structured action out. Malformed
    JSON raises ApplicationError (non-retryable) → andon, matching the
    qa-verdict shim discipline."""
    from sweep import llm_io as _llm_io, models as _models
    user = (
        f"Repo: {repo} PR #{pr}\n\n"
        f"Bot comment:\n```\n{bot_comment}\n```\n\n"
        f"Return the JSON object now."
    )
    result = await _llm_io.call(
        _models.resolve("sonnet"),
        system=_SHIM_SYSTEM, user=user,
        repo=repo, pr=pr,
        max_tokens=600, temperature=0.0,
    )
    text = (result.response or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].lstrip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ApplicationError(
            f"sign shim returned malformed JSON: {e}; first 200: {text[:200]!r}",
            non_retryable=True,
        ) from e
    for key in ("action", "comment_text", "recheck_text", "rationale"):
        if key not in data:
            raise ApplicationError(
                f"sign shim missing key {key!r}; got keys {list(data.keys())}",
                non_retryable=True,
            )
    return data


def _cla_check_status(repo: str, pr: int) -> str:
    """Return the current conclusion of the CLA-class check.
    'SUCCESS' = already signed; 'FAILURE'/'FAILED' = needs signing;
    'GONE' = no CLA check present; '?' = unknown/pending."""
    try:
        r = subprocess.run(
            ["gh", "pr", "view", str(pr), "--repo", repo,
             "--json", "statusCheckRollup"],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode != 0:
            return "?"
        data = json.loads(r.stdout or "{}")
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return "?"
    for c in data.get("statusCheckRollup") or []:
        name = (c.get("name") or c.get("context") or "").lower()
        if any(p in name for p in ("cla", "license/cla", "dco",
                                    "developer certificate",
                                    "contributor license", "sign-off")):
            conc = c.get("conclusion") or ""
            return conc if conc else "?"
    return "GONE"


def _poll_check_resolution(repo: str, pr: int, timeout_s: int = 90,
                            interval_s: int = 5) -> str:
    """Poll the CLA check's conclusion until it resolves or timeout.
    Returns the final conclusion string ("SUCCESS" / "FAILURE" /
    "TIMEOUT" / "GONE"). 90s default — CLA Assistant Lite typically
    flips within 30s."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        check = _failing_cla_check(repo, pr)
        if check is None:
            # No failing CLA check — either resolved green or removed.
            # Confirm with a second look at the rollup.
            try:
                r = subprocess.run(
                    ["gh", "pr", "view", str(pr), "--repo", repo,
                     "--json", "statusCheckRollup"],
                    capture_output=True, text=True, timeout=15,
                )
                data = json.loads(r.stdout or "{}")
                for c in data.get("statusCheckRollup") or []:
                    name = (c.get("name") or c.get("context") or "").lower()
                    if "cla" in name or "license" in name:
                        conclusion = c.get("conclusion") or ""
                        if conclusion == "SUCCESS":
                            return "SUCCESS"
                        if conclusion in ("FAILURE", "FAILED"):
                            return "FAILURE"
                # No CLA check at all anymore.
                return "GONE"
            except Exception:
                return "GONE"
        time.sleep(interval_s)
    return "TIMEOUT"


@activity.defn
async def sign_cycle(msg: Message) -> dict:
    """Process one sign card. Posts the CLA-acknowledgment + recheck
    when the bot template is recognized; escalates to human otherwise.

    Idempotent on success: if the CLA check is already SUCCESS, returns
    'noop-already-signed' without posting.

    Honors post_disabled (same gate as ping/post/comment-issue)."""
    if msg.intent == "nudge":
        return {"outcome": "nudge-noop"}
    if not msg.repo or not msg.pr:
        raise ApplicationError("sign: repo + pr required",
                               non_retryable=True)
    repo, pr = msg.repo, int(msg.pr)

    if POST_DISABLED_FLAG.exists():
        observe.event("sign_skipped_post_disabled", repo=repo, pr=pr)
        return {"outcome": "skipped-post-disabled"}

    # Monoidal: check current CLA state FIRST. Sign action is idempotent
    # when applied to an already-signed PR — return noop, don't re-post.
    current = _cla_check_status(repo, pr)
    if current == "SUCCESS":
        observe.event("sign_noop_already_signed", repo=repo, pr=pr)
        return {"outcome": "noop-already-signed"}
    if current == "GONE":
        # No CLA check at all. Andon: remit claimed there was one;
        # something drifted.
        observe.event("sign_precondition_failed", repo=repo, pr=pr,
                      reason="no-cla-check-on-pr")
        raise ApplicationError(
            f"sign: no CLA-class check found on {repo}#{pr}; upstream "
            f"router claimed one existed. Inspect via "
            f"`gh pr view {pr} --repo {repo} --json statusCheckRollup`.",
            non_retryable=True,
        )
    if current not in ("FAILURE", "FAILED", "ACTION_REQUIRED"):
        # Pending, neutral, etc. Don't sign yet; let the bot finish its
        # current run. Re-queue silently — next nudge/poll picks it up.
        observe.event("sign_noop_check_pending", repo=repo, pr=pr,
                      conclusion=current)
        return {"outcome": "noop-pending", "conclusion": current}

    # CLA check is failing. Read the bot comment + ask sonnet what to do.
    bot_body = _fetch_bot_comment(repo, pr)
    if not bot_body:
        observe.event("sign_precondition_failed", repo=repo, pr=pr,
                      reason="no-bot-comment-found")
        raise ApplicationError(
            f"sign: failing CLA check on {repo}#{pr} but no bot comment "
            f"with sign instructions found. Bot may have posted to a "
            f"check-run summary instead of a PR comment, or comment "
            f"text doesn't match our scan. Inspect manually.",
            non_retryable=True,
        )

    decision = await _ask_shim(bot_body, repo, pr)
    action = decision["action"]
    rationale = decision.get("rationale", "")
    observe.event("sign_shim_decision", repo=repo, pr=pr,
                  action=action, rationale=rationale[:200])

    if action == "unknown":
        raise ApplicationError(
            f"sign: shim couldn't determine signing procedure for "
            f"{repo}#{pr}. Rationale: {rationale}. Bot comment head: "
            f"{bot_body[:300]}",
            non_retryable=True,
        )

    if action in ("signoff-commits", "web-ui"):
        # Both require human action sweep can't take autonomously —
        # rewriting commit history (DCO) or driving a browser flow
        # (EasyCLA). Route to human inbox with the rationale so
        # operator sees what's needed. NOT an andon: this is a normal
        # "needs human" outcome (sweep correctly identified the action,
        # just can't execute it), distinct from "shim couldn't classify"
        # which is an actual substrate gap.
        from sweep.activities.skill_runner import _kick_human_decision
        try:
            await _kick_human_decision(
                repo, pr,
                signal=f"sign-{action}",
                summary=(f"CLA-class check on {repo}#{pr} needs {action}. "
                         f"{rationale}"),
                artifact_path="",
            )
        except Exception as e:
            observe.event("sign_human_route_failed", repo=repo, pr=pr,
                          error_type=type(e).__name__, error=str(e)[:200])
        observe.event("sign_routed_human", repo=repo, pr=pr,
                      action=action, rationale=rationale[:200])
        return {"outcome": f"routed-human-{action}",
                "rationale": rationale}

    if action != "post-comment":
        raise ApplicationError(
            f"sign: shim returned unknown action {action!r} for "
            f"{repo}#{pr}. Schema drift in the shim output.",
            non_retryable=True,
        )

    # post-comment path. Post the exact text the shim chose, then the
    # optional recheck trigger.
    comment_text = decision.get("comment_text", "").strip()
    recheck = decision.get("recheck_text", "").strip()
    if not comment_text:
        raise ApplicationError(
            f"sign: shim chose action=post-comment but returned empty "
            f"comment_text for {repo}#{pr}. Bot comment head: "
            f"{bot_body[:300]}",
            non_retryable=True,
        )

    try:
        r1 = subprocess.run(
            ["gh", "pr", "comment", str(pr), "--repo", repo,
             "--body", comment_text],
            capture_output=True, text=True, timeout=20,
        )
        if r1.returncode != 0:
            raise ApplicationError(
                f"sign: gh pr comment (sign) failed rc={r1.returncode}: "
                f"{(r1.stderr or '')[:200]}",
                non_retryable=False,
            )
        if recheck:
            r2 = subprocess.run(
                ["gh", "pr", "comment", str(pr), "--repo", repo,
                 "--body", recheck],
                capture_output=True, text=True, timeout=20,
            )
            if r2.returncode != 0:
                raise ApplicationError(
                    f"sign: gh pr comment (recheck) failed rc={r2.returncode}: "
                    f"{(r2.stderr or '')[:200]}",
                    non_retryable=False,
                )
    except subprocess.TimeoutExpired as e:
        raise ApplicationError(f"sign: gh comment timeout: {e}",
                               non_retryable=False) from e

    observe.event("sign_posted", repo=repo, pr=pr,
                  comment_chars=len(comment_text),
                  recheck=bool(recheck))

    outcome = _poll_check_resolution(repo, pr)
    observe.event("sign_done", repo=repo, pr=pr, outcome=outcome,
                  rationale=rationale[:200])
    return {"outcome": outcome, "action": action}
