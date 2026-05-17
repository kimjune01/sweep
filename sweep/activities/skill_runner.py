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
    from sweep import observe, gh_io
    from sweep import budget as _budget
    from sweep.activities.prospect import kick_prospect_card
    _budget.record_subprocess_estimate("triage")
    # Front-of-cycle gate: if the repo is hostile to AI contributions,
    # route to immunize and short-circuit. Catches what prospect's 24h
    # AI-policy cache missed (policy added since last refresh, or the
    # operator's kill list lagged). Investigate never sees the card.
    # Belt-and-suspenders: prospect filters most of these out at the
    # front; immunize is the safety net for the gap.
    try:
        if gh_io.repo_ai_policy(msg.repo) == "hostile":
            from sweep.activities.immunize import kick_immunize_card
            try:
                await kick_immunize_card(msg.repo, int(msg.pr),
                                         source="triage")
            except Exception as e:
                observe.event("kick_immunize_failed", site="triage_cycle",
                              repo=msg.repo, issue=msg.pr,
                              error_type=type(e).__name__,
                              error=str(e)[:200])
            observe.event("triage_decision", repo=msg.repo, issue=msg.pr,
                          decision="anti-ai",
                          reason="routed to immunize",
                          score=0)
            return {"label": "triage", "rc": 0, "decision": "anti-ai"}
    except Exception:
        pass  # never let the gate failure mask the real triage path
    try:
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
        # Artifact-first: the attestation file is /triage's durable
        # contract. Read it; if present, that's the canonical decision.
        # Stdout-based shim is a degraded-mode fallback for the case
        # where the skill ran but failed to write the file.
        from sweep import skill_result
        fresh = _read_triage_attestation(msg.repo, msg.pr)
        if fresh is not None:
            observe.event("triage_decision", repo=msg.repo, issue=msg.pr,
                          decision=fresh.get("decision", "unknown"),
                          reason=str(fresh.get("reason", ""))[:200],
                          score=fresh.get("score", 0))
            return result
        # Attestation missing — degraded mode. Try the shim on stdout
        # to salvage the decision, then routing the rejection if the
        # skill explicitly declined.
        parsed = skill_result.shim("triage", result.get("stdout_tail", ""))
        if skill_result.is_rejected(parsed):
            skill_result.record_rejection("triage", msg.__dict__, parsed)
            return result
        if parsed:
            observe.event("triage_decision", repo=msg.repo, issue=msg.pr,
                          decision=parsed.get("decision", "unknown"),
                          reason="shim-fallback: " + str(parsed.get("reason", ""))[:180],
                          score=int(parsed.get("score") or 0))
            return result
        # Neither artifact nor shim. Surface the failure mode explicitly
        # so it's visible to leakdog rather than silently lost.
        observe.event("triage_no_attestation", repo=msg.repo,
                      issue=msg.pr, rc=result.get("rc", 0))
        return result
    finally:
        # Pull signal: every triage cycle emits one card on exit,
        # regardless of outcome. Bounded by prospect_recency_window's
        # free_slots check (cheap noop when triage queue is full).
        try:
            await kick_prospect_card("triage")
        except Exception as e:
            observe.event("kick_prospect_failed", site="triage_cycle",
                          error_type=type(e).__name__, error=str(e)[:200])


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

    # Note the artifact's mtime BEFORE running so we can detect a
    # fresh write vs an old file. Artifact path convention:
    # `repo-hypotheses/<owner>__<repo>__<issue>.md` (per-issue).
    artifact = _investigate_artifact_path(msg.repo, msg.pr)
    before_mtime = artifact.stat().st_mtime if artifact.exists() else 0.0

    result = await _run_skill(["/investigate", ref], label="investigate",
                              timeout_s=1800)

    # Artifact-first: /investigate's canonical contract is the
    # hypothesis graph file. When it exists, read it and classify
    # the halt section — the artifact already names its conclusion
    # (verdict, decision, halt reason, awaiting-gate). Beats both
    # the old "mtime advanced ⇒ produced_pr" reflex (wrong: most
    # halts don't ship) and a Sonnet shim call (slower, lossy).
    after_mtime = artifact.stat().st_mtime if artifact.exists() else 0.0
    artifact_fresh = after_mtime > before_mtime
    if artifact.exists():
        classified = _classify_investigate_artifact(artifact)
        if classified:
            observe.event(
                "investigate_done", repo=msg.repo, issue=msg.pr,
                rc=result.get("rc", 0),
                produced_pr=classified["produced_pr"],
                no_fix=classified["no_fix"],
                human_gated=classified["human_gated"],
                summary=f"{classified['signal']}: {classified['summary'][:140]}",
                artifact_path=str(artifact),
                artifact_fresh=artifact_fresh,
            )
            # Side-hatch routing: a no-fix verdict with a real summary
            # is exactly the case where tissue earns its keep. Skip
            # for human_gated (the operator is the decider) and shipped
            # (PR speaks for itself). Activity-owned routing — same
            # pattern as [[H20]]: the wrapper decides, not the skill.
            if classified["no_fix"] and classified.get("summary"):
                from sweep.activities.tissue import kick_tissue_card
                try:
                    await kick_tissue_card(
                        msg.repo, int(msg.pr),
                        source="investigate",
                        signal=classified["signal"],
                    )
                except Exception as e:
                    observe.event("kick_tissue_failed",
                                  repo=msg.repo, issue=msg.pr,
                                  error_type=type(e).__name__,
                                  error=str(e)[:200])
            return result

    # Artifact missing or unclassifiable — degraded mode. Try the
    # shim on stdout.
    parsed = skill_result.shim("investigate", result.get("stdout_tail", ""))
    if skill_result.is_rejected(parsed):
        skill_result.record_rejection("investigate", msg.__dict__, parsed)
        # Side-hatch: a self-PR halt rejection often has tissue value
        # ("noticed you're on it, leaving you to it"). Route it to
        # tissue with the rejection reason as the signal. If no
        # artifact ever got written, tissue's artifact_missing screen
        # drops the card — only artifact-bearing rejections produce
        # drafts. Filter to self-PR halts only; broader policy-gate
        # rejections (kill list, AI hostile) aren't tissue-worthy.
        reason = str(parsed.get("reject_reason") or "")
        if "self-pr" in reason.lower() or "self pr" in reason.lower() \
                or "maintainer self-pr halt" in reason.lower():
            from sweep.activities.tissue import kick_tissue_card
            try:
                await kick_tissue_card(
                    msg.repo, int(msg.pr),
                    source="investigate-reject",
                    signal="self-pr-halt",
                )
            except Exception as e:
                observe.event("kick_tissue_failed",
                              site="investigate_reject",
                              repo=msg.repo, issue=msg.pr,
                              error_type=type(e).__name__,
                              error=str(e)[:200])
        return result
    if parsed:
        observe.event(
            "investigate_done", repo=msg.repo, issue=msg.pr,
            rc=result.get("rc", 0),
            produced_pr=bool(parsed.get("produced_pr")),
            no_fix=bool(parsed.get("no_fix")),
            summary="shim-fallback: " + str(parsed.get("summary", ""))[:180],
        )
        return result
    # Last-ditch heuristic so the funnel still shows *something*.
    tail = (result.get("stdout_tail") or "").lower()
    produced_pr = ("pull/" in tail or "opened pr" in tail
                   or "pushed branch" in tail or "drip-ready" in tail)
    no_fix = ("no fix" in tail or "blocked" in tail or "skip" in tail
              or "no actionable" in tail)
    observe.event(
        "investigate_done", repo=msg.repo, issue=msg.pr,
        rc=result.get("rc", 0), produced_pr=produced_pr, no_fix=no_fix,
        summary="(heuristic-fallback, no artifact and no shim parse)",
    )
    return result


def _investigate_artifact_path(repo: str, issue: int):
    """Per-issue hypothesis graph: repo-hypotheses/<owner>__<repo>__<issue>.md"""
    from pathlib import Path
    slug = repo.replace("/", "__")
    return Path("/Users/junekim/Documents/sweep/repo-hypotheses") / f"{slug}__{issue}.md"


# Vocabulary the /investigate skill actually writes into halt sections.
# Each match emits a clean outcome signal — higher quality than the
# stdout-tail heuristic, and free (one file read, no Sonnet call).
# Order matters: ship beats human-gate beats no-fix beats unknown,
# because a shipped PR is the strongest claim. Patterns are
# case-insensitive substring matches against the last ~6KB.
#
# Avoid loose URL patterns (e.g. "github.com/", "pull/") — every
# artifact links to the issue URL, so those produced false positives.
# Only match concrete ship markers the skill writes deliberately.
_INVESTIGATE_SIGNALS: list[tuple[str, list[str]]] = [
    # PR was actually opened.
    ("shipped", [
        "phase 8 — pushed", "phase 8 — shipped",
        "pushed branch", "drip-ready",
        "opened pr", "pr opened at",
    ]),
    # Fix is ready but waiting on operator decision. Includes the
    # "blocked on a decision not an investigator's to make" pattern.
    ("human-gated", [
        "awaiting human gate", "awaiting human go/no-go",
        "phase 8 (ship) — awaiting", "phase 8 — awaiting",
        "standing by for decision", "human approval", "go/no-go",
        "blocked on a decision",
    ]),
    # Investigation concluded no fix should ship.
    ("no-fix", [
        "halt, do not ship", "do not ship", "no code pr is justified",
        "stale — already implemented", "stale -- already implemented",
        "already fixed upstream", "upstream fix is real",
        "frontier: closed", "frontier closed",
        "no actionable fix", "no fix to make",
        "premise killed", "premise does not hold",
        "halted at policy gate", "maintainer self-pr",
        "prework_blocked", "[[prework_blocked]]",
        "reframe: this is",
        "## halt", "## halt reason", "## halt point",
        "verdict: stale", "verdict**: **stale",
    ]),
]


def _classify_investigate_artifact(path) -> dict | None:
    """Pattern-match the halt section of a hypothesis graph to extract
    `produced_pr`, `no_fix`, `human_gated`, and a short summary line.

    Returns None when no signal matches — caller falls back to the
    shim/heuristic path. Reads only the last ~6KB of the file; halt
    sections live at the end."""
    try:
        text = path.read_text()
    except OSError:
        return None
    if not text.strip():
        return None
    # Last chunk holds the halt section in the convention investigate uses.
    tail = text[-6000:].lower()

    matched_signal: str | None = None
    matched_pat: str = ""
    for signal, patterns in _INVESTIGATE_SIGNALS:
        for pat in patterns:
            if pat in tail:
                matched_signal = signal
                matched_pat = pat
                break
        if matched_signal:
            break
    if not matched_signal:
        return None

    # Summary: the first non-empty line of the halt-region that contains
    # the matched pattern, trimmed for the event.
    summary = matched_pat
    for line in reversed(text.splitlines()):
        line_s = line.strip()
        if not line_s:
            continue
        if matched_pat in line_s.lower():
            summary = line_s.lstrip("#").strip()
            break

    return {
        "signal": matched_signal,
        "produced_pr": matched_signal == "shipped",
        "no_fix":      matched_signal == "no-fix",
        "human_gated": matched_signal == "human-gated",
        "summary":     summary,
    }
