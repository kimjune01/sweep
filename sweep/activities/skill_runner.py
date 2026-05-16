"""Generic skill-runner activities.

Each "shell out to claude --print '/<skill>'" activity goes through
`_run_skill`, which owns the subprocess plumbing, timeout, and error
shape (FileNotFoundError / TimeoutExpired / non-zero rc → non-retryable
ApplicationError so SkillActor's andon cord catches them).

Per-skill activities (`drip_cycle`, `triage_cycle`) build their own
slash argv from the Message, then delegate. This replaces the older
per-skill activity modules (sweep/activities/drip.py) which duplicated
the same scaffold each time.

When adding a skill actor:
  1. Write the slash-argv builder.
  2. Add an `@activity.defn` here that calls `_run_skill(...)`.
  3. Register it in `worker.py`.
  4. Map `actor_name → (workflow_id, activity_name)` in
     `sweep/activities/pr_state.py::_ACTOR_WORKFLOW_IDS`.
  5. Bootstrap a SkillActor instance with that activity_name in
     `sweep/cli/lifecycle.py::_ensure_actors`.
"""

from __future__ import annotations

import asyncio
import os
import subprocess

from temporalio import activity
from temporalio.exceptions import ApplicationError

from sweep.types import Message

# Directory holding the gh shim. Prepended to PATH for skill subprocesses
# so every `gh` call inside the LLM-spawned subprocess gets stamped to
# the right actor's budget log. The shim execs the real gh after
# recording, so semantics are unchanged.
_SHIM_BIN = "/Users/junekim/Documents/sweep/bin"


async def _run_skill(slash_argv: list[str], label: str,
                     timeout_s: int = 600,
                     caller: str | None = None) -> dict:
    """Shell out to claude with a slash command. Common plumbing for
    every skill-actor activity. Returns rc + stdout tail; raises
    non-retryable ApplicationError on missing claude / timeout / failure
    so the calling actor's andon cord engages.

    Subprocess runs on a thread (`asyncio.to_thread`) so the worker's
    asyncio loop stays free to poll Temporal during long /investigate
    runs. Without this, a single 30-min skill call freezes every other
    actor and Temporal sees the worker as gone ("no poller seen").
    """
    cmd = ["claude", "--print", " ".join(slash_argv)]
    # Inject gh shim onto PATH + tag the caller so every gh call inside
    # the subprocess gets attributed to this actor's budget. Without
    # this, the LLM's gh calls vanish from per-actor accounting.
    env = os.environ.copy()
    env["PATH"] = _SHIM_BIN + os.pathsep + env.get("PATH", "")
    env["SWEEP_BUDGET_CALLER"] = caller or label
    try:
        result = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True,
            timeout=timeout_s, env=env,
        )
    except FileNotFoundError as e:
        raise ApplicationError(
            f"{label}: claude not on PATH ({e})", non_retryable=True,
        )
    except subprocess.TimeoutExpired:
        raise ApplicationError(
            f"{label}: '{' '.join(slash_argv)}' exceeded {timeout_s}s",
            non_retryable=True,
        )
    if result.returncode != 0:
        # claude --print writes diagnostics to stdout, not stderr — fall
        # back to the stdout tail when stderr is empty so andon shows why.
        detail = (result.stderr or "").strip() or (result.stdout or "").strip()
        raise ApplicationError(
            f"{label}: '{' '.join(slash_argv)}' failed (rc={result.returncode}): "
            f"{detail[-400:]}",
            non_retryable=True,
        )
    return {
        "label": label,
        "rc": result.returncode,
        "stdout_tail": (result.stdout or "")[-400:],
    }


# ------------------------------------------------------------ drip

# Drip intents map to /drip skill flags. ship/rebase both push (the
# skill handles the rebase-and-force-push case internally); close is
# a check-and-comment path, not a push.
_DRIP_FLAG = {"ship": "--push", "rebase": "--push", "close": "--check"}


@activity.defn
async def drip_cycle(msg: Message) -> dict:
    if not msg.repo:
        raise ApplicationError("drip: repo required", non_retryable=True)
    from sweep import budget as _budget, observe, skill_result
    _budget.record_subprocess_estimate("drip")
    intent = msg.intent or "ship"
    flag = _DRIP_FLAG.get(intent, "--check")
    result = await _run_skill(["/drip", msg.repo, flag], label="drip")
    # Shim Sonnet over the skill's stdout for a guaranteed outcome
    # dict. Falls back to the stdout-tail heuristics if the shim
    # can't parse (rollout transition).
    parsed = skill_result.shim("drip", result.get("stdout_tail", ""))
    if skill_result.is_rejected(parsed):
        skill_result.record_rejection("drip", msg.__dict__, parsed)
        return result
    if parsed:
        observe.event(
            "drip_done", repo=msg.repo, pr=msg.pr, intent=intent,
            rc=result.get("rc", 0),
            pushed=bool(parsed.get("pushed")),
            outcome=str(parsed.get("outcome", "")),
            reason=str(parsed.get("reason", ""))[:200],
        )
        return result
    # Heuristic fallback.
    tail = (result.get("stdout_tail") or "").lower()
    pushed = (intent in ("ship", "rebase") and result.get("rc") == 0
              and ("pushed" in tail or "opened pr" in tail
                   or "pull/" in tail or "drip-ready" in tail))
    observe.event(
        "drip_done", repo=msg.repo, pr=msg.pr, intent=intent,
        rc=result.get("rc", 0), pushed=pushed,
        outcome="(heuristic-fallback)",
    )
    return result


# ------------------------------------------------------------ triage


@activity.defn
async def triage_cycle(msg: Message) -> dict:
    """Triage one issue. /triage takes an issue ref (owner/repo#N) and
    decides whether to investigate, drop, surface, or defer. Lean — no
    fan-out, no nested /investigate; the decision is emitted as an
    event and (if investigate) enqueued via `sweep investigate enqueue`.

    Cache: if an attestation file already exists for this issue, skip
    the /triage invocation entirely and return the cached decision.
    Operator wipes ~/.sweep/attestations/triage/ to force re-triage.
    """
    if not msg.repo or not msg.pr:
        raise ApplicationError("triage: repo + issue required",
                               non_retryable=True)
    from sweep import observe
    from sweep import budget as _budget
    _budget.record_subprocess_estimate("triage")
    cached = _read_triage_attestation(msg.repo, msg.pr)
    if cached is not None:
        observe.event("triage_decision", repo=msg.repo, issue=msg.pr,
                      decision=cached.get("decision", "unknown"),
                      reason="cached:" + str(cached.get("reason", "")),
                      score=cached.get("score", 0))
        return {"label": "triage", "rc": 0, "cached": True,
                "decision": cached.get("decision")}
    ref = f"{msg.repo}#{msg.pr}"
    result = await _run_skill(["/triage", ref], label="triage", timeout_s=180)
    # Shim Sonnet over the skill's stdout to get a schema-guaranteed
    # decision dict. Subscription-friendly. Falls back to reading the
    # attestation file (and then to triage_no_attestation) so we keep
    # backward compat with skill invocations that pre-date the shim.
    from sweep import skill_result
    parsed = skill_result.shim("triage", result.get("stdout_tail", ""))
    if skill_result.is_rejected(parsed):
        # Skill declined the job. Route the original msg to the
        # rejected inbox for operator review; do NOT emit a normal
        # triage_decision (that would mark this item as decided).
        skill_result.record_rejection("triage", msg.__dict__, parsed)
        return result
    if parsed:
        observe.event("triage_decision", repo=msg.repo, issue=msg.pr,
                      decision=parsed.get("decision", "unknown"),
                      reason=str(parsed.get("reason", ""))[:200],
                      score=int(parsed.get("score") or 0))
        return result
    # Shim couldn't parse stdout. Fall back to the attestation file
    # the skill writes as a side-effect.
    fresh = _read_triage_attestation(msg.repo, msg.pr)
    if fresh is not None:
        observe.event("triage_decision", repo=msg.repo, issue=msg.pr,
                      decision=fresh.get("decision", "unknown"),
                      reason="attestation-fallback: " + str(fresh.get("reason", "")),
                      score=fresh.get("score", 0))
    else:
        observe.event("triage_no_attestation", repo=msg.repo,
                      issue=msg.pr, rc=result.get("rc", 0))
    return result


def _read_triage_attestation(repo: str, issue: int) -> dict | None:
    """Read the per-issue triage attestation if it exists. Parses the
    YAML-ish frontmatter (decision, score, reason, ts). Returns None
    when the file is missing or unparseable — caller falls through to
    the live /triage call."""
    from pathlib import Path
    slug = repo.replace("/", "__")
    path = Path.home() / ".sweep" / "attestations" / "triage" / f"{slug}__{issue}.md"
    if not path.exists():
        return None
    try:
        text = path.read_text()
    except OSError:
        return None
    # Frontmatter is between two --- lines at the top.
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 4)
    if end < 0:
        return None
    fm = text[4:end]
    out: dict = {}
    for line in fm.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip()
        v = v.strip()
        if k in ("score",):
            try:
                v = int(v)
            except ValueError:
                pass
        out[k] = v
    return out if out.get("decision") else None


# ------------------------------------------------------------ investigate


@activity.defn
async def investigate_cycle(msg: Message) -> dict:
    """Run /investigate on one issue. Long-running (full hypothesis
    graph, fan-out, adversarial review) — needs the larger timeout.

    Emits an `investigate_done` event so the funnel is legible: without
    it we can see "investigations enqueued" and "qa converged" but
    nothing between, and can't tell silent-no-fix from broken bridge."""
    if not msg.repo or not msg.pr:
        raise ApplicationError("investigate: repo + issue required",
                               non_retryable=True)
    ref = f"{msg.repo}#{msg.pr}"
    from sweep import budget as _budget, observe, skill_result
    _budget.record_subprocess_estimate("investigate")
    result = await _run_skill(["/investigate", ref], label="investigate",
                              timeout_s=1800)
    # Shim first: ask Sonnet to extract the structured outcome from
    # the skill's stdout. Falls back to the original stdout-tail
    # heuristics when the shim can't parse (so we still get partial
    # signal during the rollout window when skills haven't been
    # taught to emit JSON yet).
    parsed = skill_result.shim("investigate", result.get("stdout_tail", ""))
    if skill_result.is_rejected(parsed):
        skill_result.record_rejection("investigate", msg.__dict__, parsed)
        return result
    if parsed:
        observe.event(
            "investigate_done", repo=msg.repo, issue=msg.pr,
            rc=result.get("rc", 0),
            produced_pr=bool(parsed.get("produced_pr")),
            no_fix=bool(parsed.get("no_fix")),
            summary=str(parsed.get("summary", ""))[:200],
        )
        return result
    # Heuristic fallback (pre-shim behavior).
    tail = (result.get("stdout_tail") or "").lower()
    produced_pr = ("pull/" in tail or "opened pr" in tail
                   or "pushed branch" in tail or "drip-ready" in tail)
    no_fix = ("no fix" in tail or "blocked" in tail or "skip" in tail
              or "no actionable" in tail)
    observe.event(
        "investigate_done", repo=msg.repo, issue=msg.pr,
        rc=result.get("rc", 0), produced_pr=produced_pr, no_fix=no_fix,
        summary="(heuristic-fallback, shim parse failed)",
    )
    return result
