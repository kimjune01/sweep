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
import subprocess

from temporalio import activity
from temporalio.exceptions import ApplicationError

from sweep.types import Message


async def _run_skill(slash_argv: list[str], label: str,
                     timeout_s: int = 600) -> dict:
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
    try:
        result = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True, timeout=timeout_s,
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
    flag = _DRIP_FLAG.get(msg.intent or "ship", "--check")
    return await _run_skill(["/drip", msg.repo, flag], label="drip")


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
    # Emit the decision event ourselves by re-reading the attestation
    # the skill just wrote. Don't trust the skill to call observe.event
    # — that was the structural leak (79/80 acked items emitted no
    # event because the skill silently skipped its own logging).
    fresh = _read_triage_attestation(msg.repo, msg.pr)
    if fresh is not None:
        observe.event("triage_decision", repo=msg.repo, issue=msg.pr,
                      decision=fresh.get("decision", "unknown"),
                      reason=str(fresh.get("reason", "")),
                      score=fresh.get("score", 0))
    else:
        # No attestation after the skill ran = the skill failed to
        # decide. Surface that as its own event so we can see this
        # failure mode in the manifest instead of just losing the item.
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
    from sweep import observe
    result = await _run_skill(["/investigate", ref], label="investigate",
                              timeout_s=1800)
    # Heuristic: /investigate's terminal lines usually mention either
    # the opened PR ("opened https://github.com/..." or "branch ...
    # pushed") or a no-fix verdict ("no fix", "BLOCKED", "skip").
    # Stamp both signals so the post-hoc funnel can tell them apart.
    tail = (result.get("stdout_tail") or "").lower()
    produced_pr = ("pull/" in tail or "opened pr" in tail
                   or "pushed branch" in tail or "drip-ready" in tail)
    no_fix = ("no fix" in tail or "blocked" in tail or "skip" in tail
              or "no actionable" in tail)
    observe.event(
        "investigate_done", repo=msg.repo, issue=msg.pr,
        rc=result.get("rc", 0), produced_pr=produced_pr, no_fix=no_fix,
    )
    return result
