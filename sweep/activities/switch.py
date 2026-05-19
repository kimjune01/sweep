"""classify — investigation-artifact classifier as an actor.

Reads one hypothesis-graph artifact, asks Sonnet (via claude CLI / Max
plan) to judge the conclusion, routes the card downstream:

  shipped     → qa (if branch on remote; ghost_branch event otherwise)
  no-fix      → comment-issue (skill SKIPs if quality bar not met)
  human-gated → human inbox

Was inline in `investigate_cycle` and `reinvestigate_cycle`. Promoted
to an actor because:
- Decouples LLM latency (~4s) from the production-lane takt
- Reclassification on prompt change becomes an actor signal, not a
  long-running CLI batch
- Cockpit's classify row will show queue depth + throughput
- Same shape can serve any artifact-producing upstream (today
  investigate + reinvestigate; potentially attest, qa, others)

The classifier function itself (`switch_artifact`) is callable
synchronously for the rare cases that need inline judgment (the CLI
batch can still use it directly with the same cache).
"""

from __future__ import annotations

import datetime as dt
import hashlib
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


SWITCH_INBOX = Path.home() / ".sweep" / "inbox" / "switch.jsonl"
SWITCH_CACHE_PATH = Path.home() / ".sweep" / "switch-cache.json"


# ---------------------------------------------------------------- classifier

_SYSTEM_PROMPT = """\
You're the central switch for an investigation artifact (hypothesis graph).
Read the FULL artifact, judge the conclusion, return JSON with a routing
verdict and a should_comment flag.

Routing bias: prefer "shipped" whenever a verified fix exists. The qa stage
downstream has further adversarial review + attest gate + compose + operator
approve at submit — those filter borderline cases. Sending TO qa is cheap;
sending to human stops flow and requires manual operator triage. So when in
doubt between "shipped" and "human-gated" for a verified fix, choose shipped.

Signals:
- "shipped": verified fix exists, no significant competing PR. Goes to qa.
  Cues: fail-on-main confirmed, pass-on-fix confirmed, "## Verification",
  "## Diff shape" with files touched, "recommendation: ship", phase-8
  markers, readiness record path, "## Halt" with a concrete fix described.

- "ship-vs-competing": verified fix AND a competing PR is mentioned AND on
  vibes-comparison ours is better (smaller diff, cleaner approach, matches
  project convention more closely, addresses root cause more directly).
  Same route as "shipped" → qa, flagged for hypothesis tracking.

- "defer-competing": competing PR OR existing engagement is mentioned AND
  the issue is already being worked. This covers three shapes:
    (a) another contributor's PR addresses the same issue
    (b) the issue is self-assigned to the operator (assignee = our user)
        or otherwise marked "in progress" — the operator is already on it
    (c) a prior PR by our substrate exists for this issue
  Do NOT open a new one. Default silent — set should_comment=true ONLY
  when the artifact contains a fact the existing work missed, a heads-up
  the maintainer needs, or a small concrete suggestion. "We also looked!"
  ego-noise is NOT a reason to comment.

- "no-fix": no PR should be opened, no competing PR. Cues: already fixed
  upstream, frontier closed, premise killed, bug doesn't reproduce,
  stale-and-resolved, explicit "halt — do not ship". should_comment is
  often true here — the investigation's findings have maintainer value.

- "human-gated": automation can't progress — CLA/DCO/sign-off blocker,
  multiple equally-valid paths with no convention, reporter-is-maintainer,
  explicit "awaiting human go/no-go". Last resort for mid-investigation
  with no terminal verdict.

When you see a competing PR mentioned (phrases like "competing PR",
"existing PR", "another contributor's PR", "open PR #N from @user"),
choose "ship-vs-competing" or "defer-competing" — never plain "shipped"
or "no-fix". The competition signal is too important to lose.

Halt vocabulary — read the artifact's LAST sections (## Frontier, ## Verdict,
## Re-entry, ## Final, ## Pruning Log, ## Halt) for the terminal call:

- "tissue-class, no PR" / "Route: /tissue" / "Route: tissue" → no-fix
  (these explicitly mean "leave a comment, don't open a PR"). Set
  should_comment=true; the investigation has maintainer value.
- "no_fix_to_ship" / "no fix to ship" → no-fix.
- "Single docs commit ships." / "<N> commit(s) ships." → shipped.
- "Single PR ships" / "PR shipped at <ref>" → shipped (or
  ship-vs-competing if a competing PR is also named).
- "Halt." (terminal, by itself) at the end of artifact → no-fix.
- "Verdict unchanged: <X>" → treat as <X>'s implied routing
  (X="tissue-class, no PR" → no-fix; X="ship" → shipped).
- A "Pruning Log" listing H₀-H₆ kept open as "frontier" alongside
  killed hypotheses is NOT a verdict — that's the bookkeeping. Ignore
  "kept open as a frontier" lines unless they ARE the verdict.

When the artifact contains BOTH a verified-fix section (## Diagnosis +
## Plan + concrete patch) AND a frontier section saying the fix should
ship → shipped, not no-fix.

should_comment guidance:
- shipped / ship-vs-competing: false (qa speaks for itself)
- defer-competing: true ONLY if the artifact has substantive add for the
  maintainer beyond "we agree with their approach"
- no-fix: true if the artifact has a maintainer-useful finding (root cause,
  upstream fix pointer, duplicate ref, reproducer, workaround); false if
  the conclusion is uninformative
- human-gated: false (operator decides whether to comment)

Output ONLY a JSON object matching this shape:
{
  "signal": "shipped" | "ship-vs-competing" | "defer-competing" | "no-fix" | "human-gated",
  "summary": "<one short sentence; <=150 chars>",
  "competing_pr": "<owner/repo#N if mentioned, else empty string>",
  "should_comment": true | false
}
"""


def _load_cache() -> dict:
    if not SWITCH_CACHE_PATH.exists():
        return {}
    try:
        return json.loads(SWITCH_CACHE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(cache: dict) -> None:
    try:
        SWITCH_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        SWITCH_CACHE_PATH.write_text(json.dumps(cache))
    except OSError:
        pass


def _parse_json(stdout: str) -> dict | None:
    """Extract verdict JSON from claude's print output."""
    s = (stdout or "").strip()
    try:
        obj = json.loads(s)
        if isinstance(obj, dict) and "signal" in obj:
            return obj
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", s, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict) and "signal" in obj:
                return obj
        except json.JSONDecodeError:
            pass
    m = re.search(r"\{[^{}]*\"signal\"[^{}]*\}", s, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict) and "signal" in obj:
                return obj
        except json.JSONDecodeError:
            pass
    return None


def _materialize(parsed: dict) -> dict:
    """Expand the verdict JSON into the full shape. Five signals collapse
    into three routing targets:
      shipped + ship-vs-competing → qa
      defer-competing             → silent (or comment-issue if should_comment)
      no-fix                      → comment-issue (if should_comment)
      human-gated                 → human inbox
    The ship-vs-competing and defer-competing variants stay distinct in
    the event log so we can measure the vibes-judgment hypothesis."""
    signal = parsed.get("signal", "human-gated")
    return {
        "signal":         signal,
        "produced_pr":    signal in ("shipped", "ship-vs-competing"),
        "no_fix":         signal == "no-fix",
        "human_gated":    signal == "human-gated",
        "defer_competing": signal == "defer-competing",
        "competing_pr":   parsed.get("competing_pr", ""),
        "should_comment": bool(parsed.get("should_comment", False)),
        "summary":        parsed.get("summary", "")[:200],
    }


def switch_artifact(path: Path) -> dict | None:
    """Sync entry point — read artifact, return verdict dict or None.
    Cached by content hash. Falls back to a generic human-gated verdict
    if claude is unavailable so the routing path never silently drops."""
    try:
        text = path.read_text()
    except OSError:
        return None
    if not text.strip():
        return None
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    cache = _load_cache()
    if content_hash in cache:
        return _materialize(cache[content_hash])

    if len(text) > 30_000:
        text = text[:6_000] + "\n\n[... truncated ...]\n\n" + text[-24_000:]

    from sweep.claude_subprocess import env_without_api_key as _env_no_key
    env = _env_no_key()

    # Retry once on transient failures (timeout / non-zero rc / unparseable
    # JSON). FileNotFoundError isn't transient — claude is missing — surface
    # immediately. Subprocess crashes were silently degrading to
    # human-gated and noising the operator inbox; a single retry covers
    # most flake without burning much budget.
    last_fail: tuple[str, str] | None = None
    for attempt in (1, 2):
        try:
            proc = subprocess.run(
                ["claude", "--print", "--model", "claude-sonnet-4-6",
                 "--append-system-prompt", _SYSTEM_PROMPT, text],
                capture_output=True, text=True, timeout=60, check=False,
                env=env,
            )
        except FileNotFoundError:
            return _materialize({"signal": "human-gated",
                                 "summary": "classify: claude unavailable, "
                                            "operator review fallback"})
        except subprocess.TimeoutExpired:
            last_fail = ("timeout", "classify: claude timeout")
            observe.event("switch_classifier_retry", attempt=attempt,
                          reason="timeout")
            continue
        if proc.returncode != 0:
            last_fail = ("rc", f"classify: claude rc={proc.returncode}")
            observe.event("switch_classifier_retry", attempt=attempt,
                          reason="rc", rc=proc.returncode)
            continue
        parsed = _parse_json(proc.stdout or "")
        if parsed is None:
            last_fail = ("unparseable", "classify: unparseable verdict, "
                                         "operator review fallback")
            observe.event("switch_classifier_retry", attempt=attempt,
                          reason="unparseable")
            continue
        cache[content_hash] = parsed
        _save_cache(cache)
        return _materialize(parsed)

    # Both attempts failed. Surface as human-gated with the last failure's
    # summary so the operator can see whether it was timeout / rc / parse.
    reason, summary = last_fail or ("unknown", "classify: unknown failure")
    observe.event("switch_classifier_failed_after_retry",
                  reason=reason, summary=summary)
    return _materialize({"signal": "human-gated", "summary": summary})


# ---------------------------------------------------------------- kick

async def kick_switch_card(repo: str, issue: int, *,
                              artifact_path: str,
                              source: str,
                              incoming: Message | None = None) -> str | None:
    """Deposit one classification card. Called from investigate /
    reinvestigate after the artifact is written, and from the retro
    reclassify CLI for batch re-routing."""
    from sweep.activities.pr_state import _signal_actor
    ts = dt.datetime.now(dt.timezone.utc)
    msg = Message(
        msg_id=f"switch-{repo.replace('/', '-')}-{issue}-{ts.strftime('%Y%m%dT%H%M%S')}",
        sender=source,
        intent="switch",
        repo=repo, pr=issue, branch=None,
        payload={"artifact_path": artifact_path, "source": source},
        ts=ts.isoformat(),
        ledger=forward_ledger(incoming),
    )
    SWITCH_INBOX.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(SWITCH_INBOX, "a") as f:
            f.write(json.dumps(asdict(msg)) + "\n")
    except OSError as e:
        observe.event("switch_card_write_failed", repo=repo, issue=issue,
                      error_type=type(e).__name__, error=str(e)[:200])
        return None
    observe.event("switch_card_deposited", repo=repo, issue=issue,
                  artifact_path=artifact_path, source=source,
                  msg_id=msg.msg_id)
    return await _signal_actor("switch", msg)


# ---------------------------------------------------------------- activity

@activity.defn
async def switch_cycle(msg: Message) -> dict:
    """Classify one artifact, route the card downstream.

    Emits one terminal event:
      - switch_done  — verdict + routing target
      - switch_skipped — artifact missing or malformed
    """
    if not msg.payload or "artifact_path" not in msg.payload:
        raise ApplicationError("classify: artifact_path required",
                               non_retryable=True)
    repo = msg.repo or ""
    issue = msg.pr or 0
    art_path = Path(msg.payload["artifact_path"])
    if not art_path.exists():
        observe.event("switch_skipped", repo=repo, issue=issue,
                      reason="artifact_missing",
                      artifact_path=str(art_path))
        return {"skipped": "artifact_missing"}

    verdict = switch_artifact(art_path)
    if verdict is None:
        observe.event("switch_skipped", repo=repo, issue=issue,
                      reason="artifact_empty_or_unreadable",
                      artifact_path=str(art_path))
        return {"skipped": "artifact_empty"}

    observe.event("switch_done", repo=repo, issue=issue,
                  signal=verdict["signal"],
                  competing_pr=verdict.get("competing_pr", ""),
                  should_comment=verdict.get("should_comment", False),
                  summary=verdict.get("summary", "")[:200],
                  artifact_path=str(art_path))

    routed_to = await _route(repo, issue, verdict, str(art_path), msg)

    # Supersede legacy human-inbox cards: when switch reaches a
    # non-human verdict for this (repo, issue), any pre-existing
    # investigate-decision card in the human inbox is now obsolete.
    # Ack it so the operator's inbox reflects switch's current call,
    # not the historical inline-classifier punt. The msg_id pattern
    # is investigate-decision-<slug>-<issue>-<signal>; we ack across
    # the signal variants that the legacy code emitted.
    if not verdict.get("human_gated") and routed_to != "human":
        _ack_legacy_human_cards(repo, issue)

    return {"signal": verdict["signal"], "routed_to": routed_to,
            "competing_pr": verdict.get("competing_pr", ""),
            "summary": verdict.get("summary", "")[:200]}


def _ack_legacy_human_cards(repo: str, issue: int) -> None:
    """Append acks for any investigate-decision human-inbox cards that
    cover this (repo, issue). Idempotent — appending an ack for a
    non-existent msg_id is a no-op in inbox_state's set lookup."""
    import datetime as _dt
    slug = repo.replace("/", "-")
    legacy_signals = (
        "unclassified", "human-gated", "human_gated",
        "shipped", "no-fix",
    )
    ack_file = Path.home() / ".sweep" / "inbox" / "_acks.jsonl"
    ack_file.parent.mkdir(parents=True, exist_ok=True)
    now_iso = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    try:
        with ack_file.open("a") as f:
            for sig in legacy_signals:
                msg_id = f"investigate-decision-{slug}-{issue}-{sig}"
                f.write(json.dumps({
                    "msg_id": msg_id,
                    "acked_at": now_iso,
                    "by": "switch-supersede",
                }) + "\n")
    except OSError as e:
        observe.event("switch_legacy_ack_failed", repo=repo, issue=issue,
                      error_type=type(e).__name__, error=str(e)[:200])


async def _route(repo: str, issue: int, verdict: dict,
                 artifact_path: str, incoming: Message) -> str:
    """Routing contract:
      shipped / ship-vs-competing → qa (with metadata for the hypothesis)
      defer-competing             → silent by default; comment-issue iff
                                    should_comment=true (substantive add)
      no-fix                      → comment-issue iff should_comment=true;
                                    silent otherwise (uninformative finding)
      human-gated                 → human inbox
    Returns the actor name routed to ('silent-defer'/'silent-no-fix' for
    the deliberately-no-action paths so the operator can grep them)."""
    if verdict.get("produced_pr"):
        # Need a branch to feed qa. Mirror the lookup investigate did
        # inline: worktree → git rev-parse → ls-remote check.
        try:
            from sweep.activities.worktree import _safe_dir
            wt = _safe_dir(repo)
            branch = ""
            if wt.exists():
                br_out = subprocess.run(
                    ["git", "-C", str(wt), "rev-parse",
                     "--abbrev-ref", "HEAD"],
                    capture_output=True, text=True, timeout=5,
                )
                if br_out.returncode == 0:
                    branch = br_out.stdout.strip()
            if branch and branch not in ("HEAD", "main", "master"):
                ls = subprocess.run(
                    ["git", "-C", str(wt), "ls-remote", "--heads", "origin",
                     branch], capture_output=True, text=True, timeout=10,
                )
                if ls.returncode == 0 and ls.stdout.strip():
                    from sweep.activities.qa import kick_qa_card
                    await kick_qa_card(repo, branch,
                                       sender="switch", incoming=incoming)
                    return "qa"
            # No branch / branch not on origin. Don't fall through to
            # human — for reclassified historical artifacts, the work
            # already happened in the past; routing to human would
            # pollute the inbox with stale-shipped cards. Emit the
            # ghost_branch event so retro/leakdog can see the gap.
            observe.event("ghost_branch", repo=repo, issue=issue,
                          branch=branch,
                          reason="switch: shipped verdict but no branch "
                                 "on origin (likely stale reclassification)")
            return "silent-ghost"
        except Exception as e:
            observe.event("switch_route_failed", repo=repo, issue=issue,
                          target="qa", error_type=type(e).__name__,
                          error=str(e)[:200])
            return "silent-route-error"

    # no-fix or defer-competing: comment-issue iff should_comment=true,
    # otherwise silent (event already emitted; nothing further to do).
    if verdict.get("no_fix") or verdict.get("defer_competing"):
        if not verdict.get("should_comment"):
            return ("silent-defer" if verdict.get("defer_competing")
                    else "silent-no-fix")
        try:
            from sweep.activities.comment_issue import kick_comment_issue_card
            await kick_comment_issue_card(
                repo, int(issue),
                source="switch", signal=verdict["signal"],
                incoming=incoming,
            )
            return "comment-issue"
        except Exception as e:
            observe.event("switch_route_failed", repo=repo, issue=issue,
                          target="comment-issue",
                          error_type=type(e).__name__, error=str(e)[:200])

    # human-gated (or any fall-through)
    return await _route_human(repo, issue, verdict, artifact_path)


async def _route_human(repo: str, issue: int, verdict: dict,
                       artifact_path: str) -> str:
    try:
        from sweep.activities.skill_runner import _kick_human_decision
        await _kick_human_decision(
            repo, issue,
            signal=verdict.get("signal", "unclassified"),
            summary=verdict.get("summary", "") or
                    f"{verdict.get('signal', 'unclassified')}: "
                    "(no halt-line extracted)",
            artifact_path=artifact_path,
        )
        return "human"
    except Exception as e:
        observe.event("switch_route_failed", repo=repo, issue=issue,
                      target="human", error_type=type(e).__name__,
                      error=str(e)[:200])
        return "route_failed"
