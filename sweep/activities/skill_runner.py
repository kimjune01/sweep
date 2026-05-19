"""Generic skill-runner activities.

Each "shell out to claude --print '/<skill>'" activity goes through
`_run_skill`, which owns the subprocess plumbing, timeout, and error
shape (FileNotFoundError / TimeoutExpired / non-zero rc → non-retryable
ApplicationError so SkillActor's andon cord catches them).

Per-skill activities (`respond_cycle`, `triage_cycle`) build their own
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
import datetime
import json
import os
import subprocess
from pathlib import Path

from temporalio import activity
from temporalio.exceptions import ApplicationError

from sweep.types import Message

# Directory holding the gh shim. Prepended to PATH for skill subprocesses
# so every `gh` call inside the LLM-spawned subprocess gets stamped to
# the right actor's budget log. The shim execs the real gh after
# recording, so semantics are unchanged.
_SHIM_BIN = "/Users/junekim/Documents/sweep/bin"

# Skills directory. Codex runner reads markdown directly from here
# (Claude runner loads it implicitly via its slash-command system).
_SKILLS_DIR = "/Users/junekim/Documents/sweep/skills"


def _codex_skill_prompt(slash_argv: list[str]) -> str:
    """Render a skill's markdown body + the invocation args as a single
    prompt string for `codex exec -`. Strips the Claude-specific
    frontmatter (--- block) since codex doesn't parse it. The argv tail
    (everything after the slash command) becomes a closing "Task:" line
    so codex sees the same arguments the Claude runner would.

    Falls back to the raw argv joined as a one-line prompt if the skill
    file is missing — preserves the behavior of "run something" even
    when the skill content can't be loaded."""
    import os as _os
    if not slash_argv:
        return ""
    head = slash_argv[0].lstrip("/")
    args = " ".join(slash_argv[1:])
    skill_path = _os.path.join(_SKILLS_DIR, f"{head}.md")
    try:
        with open(skill_path) as f:
            body = f.read()
    except OSError:
        return f"Run skill /{head} with args: {args}"
    if body.startswith("---"):
        end = body.find("\n---", 3)
        if end != -1:
            body = body[end + 4:].lstrip()
    return f"{body}\n\n---\n\nTask: {args}\n"


async def _run_skill(slash_argv: list[str], label: str,
                     timeout_s: int = 600,
                     caller: str | None = None,
                     runner: str = "claude",
                     extra_env: dict[str, str] | None = None) -> dict:
    """Shell out to a skill runner with a slash-style command. Common
    plumbing for every skill-actor activity. Returns rc + stdout tail;
    raises non-retryable ApplicationError on missing CLI / timeout /
    failure so the calling actor's andon cord engages.

    Subprocess runs on a thread (`asyncio.to_thread`) so the worker's
    asyncio loop stays free to poll Temporal during long /investigate
    runs. Without this, a single 30-min skill call freezes every other
    actor and Temporal sees the worker as gone ("no poller seen").

    Runner choice:
      - "claude"  → `claude --print "/<skill> args..."` (default). Loads
                    the skill's frontmatter (allowed-tools, etc.) and
                    runs as a full Claude Code session with tool access.
      - "codex"   → Read the skill markdown directly, strip frontmatter,
                    append the argv as the user task, pipe to
                    `codex exec -`. Codex runs the same instructions
                    using its own tool model. Used when investigate_primary
                    resolves to codex (the openai provider).
    """
    if runner == "codex":
        cmd = ["codex", "exec", "-"]
        codex_input = _codex_skill_prompt(slash_argv)
    else:
        cmd = ["claude", "--print", " ".join(slash_argv)]
        codex_input = None
    # Inject gh shim onto PATH + tag the caller so every gh call inside
    # the subprocess gets attributed to this actor's budget. Without
    # this, the LLM's gh calls vanish from per-actor accounting.
    from sweep.claude_subprocess import env_without_api_key
    env = env_without_api_key()  # OAuth → Max plan; no API credit burn
    env["PATH"] = _SHIM_BIN + os.pathsep + env.get("PATH", "")
    env["SWEEP_BUDGET_CALLER"] = caller or label
    if extra_env:
        env.update(extra_env)
    # Append one line per claude invocation so the wasteboard can
    # surface the 5h-quota burn rate. The Claude Code SaaS quota is
    # invisible to us (no programmatic API); subprocess-call count is
    # the cheapest proxy. Append-only; never read in the hot path.
    try:
        import datetime as _dt
        from pathlib import Path as _Path
        _log = _Path.home() / ".sweep" / "claude_calls.jsonl"
        _log.parent.mkdir(parents=True, exist_ok=True)
        with open(_log, "a") as _f:
            _f.write(json.dumps({
                "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                "label": label,
                "argv": slash_argv,
            }) + "\n")
    except Exception:
        pass
    try:
        result = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True,
            timeout=timeout_s, env=env, input=codex_input,
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

# Drip intents map to /drip skill flags. publish (new PR creation +
# first push) and rebase both invoke --push (the skill handles the
# rebase-and-force-push case internally); close is a check-and-comment
# path, not a push.
#
# Note: `publish` is the only new-public-commitment intent and is
# normally consumed by submit-actor (which adds the dry-mode hold and
# final pre-push checks). respond_cycle is the underlying activity for
# the push mechanism — submit-actor delegates to it, and respond-actor
# itself receives publish only on legacy direct routing.
_DRIP_FLAG = {"publish": "--push", "rebase": "--push", "close": "--check"}


@activity.defn
async def respond_cycle(msg: Message) -> dict:
    if not msg.repo:
        raise ApplicationError("drip: repo required", non_retryable=True)
    from sweep import budget as _budget, observe, skill_result
    _budget.record_subprocess_estimate("respond")
    intent = msg.intent or "publish"
    flag = _DRIP_FLAG.get(intent, "--check")

    # Attestation gate: any push intent (publish, rebase) needs a
    # verified attestation in the worktree's prework/ dir. Close
    # intents don't (no code claim being made). Defense in depth —
    # submit-actor gates first, but respond-actor catches direct
    # routings (CHANGES_REQUESTED → respond via remit, which bypasses
    # submit entirely).
    if intent in ("publish", "rebase") and msg.branch:
        from sweep.activities.submit import _attestation_gate
        ok, reason = await _attestation_gate(msg.repo, msg.branch)
        if not ok:
            observe.event("respond_attestation_failed", repo=msg.repo,
                          branch=msg.branch, pr=msg.pr, intent=intent,
                          reason=reason, msg_id=msg.msg_id)
            return {"rc": 1, "pushed": False, "gated": True,
                    "reason": f"attestation: {reason}"}

    result = await _run_skill(["/drip", msg.repo, flag], label="respond")
    # Shim Sonnet over the skill's stdout for a guaranteed outcome
    # dict. Falls back to the stdout-tail heuristics if the shim
    # can't parse (rollout transition).
    parsed = skill_result.shim("drip", result.get("stdout_tail", ""))
    if skill_result.is_rejected(parsed):
        skill_result.record_rejection("drip", msg.__dict__, parsed)
        return result
    if parsed:
        pushed_flag = bool(parsed.get("pushed"))
        observe.event(
            "respond_done", repo=msg.repo, pr=msg.pr, intent=intent,
            rc=result.get("rc", 0),
            pushed=pushed_flag,
            outcome=str(parsed.get("outcome", "")),
            reason=str(parsed.get("reason", ""))[:200],
        )
        if pushed_flag and intent == "publish":
            _invalidate_org_state_cache(msg.repo)
        return result
    # Heuristic fallback.
    tail = (result.get("stdout_tail") or "").lower()
    pushed = (intent in ("publish", "rebase") and result.get("rc") == 0
              and ("pushed" in tail or "opened pr" in tail
                   or "pull/" in tail or "drip-ready" in tail))
    observe.event(
        "respond_done", repo=msg.repo, pr=msg.pr, intent=intent,
        rc=result.get("rc", 0), pushed=pushed,
        outcome="(heuristic-fallback)",
    )
    if pushed and intent == "publish":
        _invalidate_org_state_cache(msg.repo)
    return result


def _invalidate_org_state_cache(repo: str) -> None:
    """After we publish a new PR, refetch this org from gh and write
    it through to cache. The next gate read sees the new PR
    immediately with no race. Per-org fetch is one scoped gh call.
    The wild #1924 era let two PRs land in kimjune01/sptlrx 4m25s
    apart because the old TTL cache hadn't expired between checks;
    write-through closes that window structurally."""
    try:
        from sweep import org_state, observe
        org = org_state.org_of(repo)
        org_state.refresh_org(org)
        observe.event("org_state_refreshed", repo=repo, org=org,
                      reason="post-publish")
    except Exception as e:
        from sweep import observe
        observe.event("org_state_refresh_failed", repo=repo,
                      error_type=type(e).__name__, error=str(e)[:200])


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
    from sweep import observe, gh_io, pokayoke
    from sweep import budget as _budget
    from sweep.activities.roll import kick_roll_card
    _budget.record_subprocess_estimate("triage")
    # Front-of-cycle pokayoke gate. Sift filters at deposit time, but
    # in-flight cards from before eviction still land here; the intake
    # contract is the activity-side backstop.
    skip = pokayoke.triage_intake(msg)
    if skip:
        observe.event("triage_decision", repo=msg.repo, issue=msg.pr,
                      decision=skip.code, reason=skip.detail, score=0)
        return {"label": "triage", "rc": 0, "decision": skip.code,
                "reason": skip.detail}
    # Front-of-cycle gate: if the repo is hostile to AI contributions,
    # route to immunize and short-circuit. Catches what sift's 24h
    # AI-policy cache missed (policy added since last refresh, or the
    # operator's kill list lagged). Investigate never sees the card.
    # Belt-and-suspenders: sift filters most of these out at the
    # front; immunize is the safety net for the gap.
    try:
        if gh_io.repo_ai_policy(msg.repo) == "hostile":
            from sweep.activities.immunize import kick_immunize_card
            try:
                await kick_immunize_card(msg.repo, int(msg.pr),
                                         source="triage",
                                         incoming=msg)
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

    # Host-compat gate: when the issue's title/labels mention a
    # platform/stack we can't reproduce in our linux-docker env
    # (CUDA, Windows-only APIs, kernel modules, etc.), evict the
    # whole repo. One such issue per repo is enough — the project
    # has a dimension we'd just hit at the test-env gate anyway.
    # Cheap pre-LLM check; no token cost.
    try:
        view = gh_io.issue_view(msg.repo, int(msg.pr),
                                fields="title,labels")
        reason = _host_incompat_signal(
            view.get("title", ""), view.get("labels", []))
        if reason:
            _evict_repo(msg.repo, reason)
            observe.event("triage_decision", repo=msg.repo, issue=msg.pr,
                          decision="evicted",
                          reason=reason,
                          score=0)
            return {"label": "triage", "rc": 0, "decision": "evicted",
                    "reason": reason}
    except Exception:
        pass  # gate-failure must never mask the real triage path

    # Outside-PR-hostility gate: small internal team + high fork-to-
    # contributor ratio = product-shaped repo where outside PRs land in
    # feature-request purgatory. One gh api call per repo lifetime
    # (cached). Witnessed on pingcap/ossinsight.
    try:
        reason = _outside_pr_hostility_check(msg.repo)
        if reason:
            _evict_repo(msg.repo, reason)
            observe.event("triage_decision", repo=msg.repo, issue=msg.pr,
                          decision="evicted",
                          reason=reason,
                          score=0)
            return {"label": "triage", "rc": 0, "decision": "evicted",
                    "reason": reason}
    except Exception:
        pass  # gate-failure must never mask the real triage path

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
            decision = fresh.get("decision", "unknown")
            reason = str(fresh.get("reason", ""))[:200]
            observe.event("triage_decision", repo=msg.repo, issue=msg.pr,
                          decision=decision, reason=reason,
                          score=fresh.get("score", 0))
            # env-blocked: substrate can't repro on this host. Append
            # the repo to sift_evicted.txt so future cards bounce at
            # sift/pokayoke. Mirrors switch's env_blocked path —
            # triage catches what's visible from the issue body alone,
            # switch catches what only surfaces post-investigation.
            if decision == "env-blocked":
                try:
                    from pathlib import Path
                    import datetime as _dt
                    evicted_path = Path.home() / ".sweep" / "control" / "sift_evicted.txt"
                    evicted_path.parent.mkdir(parents=True, exist_ok=True)
                    existing = evicted_path.read_text() if evicted_path.exists() else ""
                    already = any(
                        ln.split("#")[0].strip() == msg.repo
                        for ln in existing.splitlines() if ln.strip()
                    )
                    if not already:
                        ts = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
                        with open(evicted_path, "a") as f:
                            f.write(f"{msg.repo}  # auto-evicted {ts} "
                                    f"(triage env-blocked: {reason[:120]})\n")
                        observe.event("triage_env_evict",
                                      repo=msg.repo, issue=msg.pr,
                                      reason=reason[:120])
                except Exception as e:
                    observe.event("triage_env_evict_failed",
                                  repo=msg.repo, issue=msg.pr,
                                  error_type=type(e).__name__,
                                  error=str(e)[:200])
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
        # Pull signal: route through rope (the depth controller) instead
        # of kicking roll directly. Rope reads roll.jsonl depth and
        # decides whether to fire; one idle signal in, zero-or-one roll
        # card out. This converges all pull signals on a single throttle
        # point so the line doesn't over-fire from multiple callers.
        try:
            from sweep.activities.rope import kick_rope_card
            await kick_rope_card("triage", incoming=msg)
        except Exception as e:
            observe.event("kick_rope_failed", site="triage_cycle",
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
    # Metronome nudges arrive via the same deliver signal as real cards
    # but carry intent="nudge" + empty repo/pr. They mean "check your
    # inbox" — return a no-op so the actor's run loop continues into
    # the next inbox pull. Same handling in reinvestigate_cycle and
    # sign_cycle.
    if msg.intent == "nudge":
        return {"outcome": "nudge-noop"}
    if not msg.repo or not msg.pr:
        raise ApplicationError("investigate: repo + issue required",
                               non_retryable=True)

    # Pokayoke gate — skip evicted/killed repos before any work.
    from sweep import pokayoke as _pokayoke
    _skip = _pokayoke.investigate_intake(msg)
    if _skip:
        observe.event("investigate_done", repo=msg.repo, issue=msg.pr,
                      rc=0, produced_pr=False, no_fix=True,
                      human_gated=False,
                      summary=f"skipped: {_skip.detail}")
        return {"label": "investigate", "rc": 0, "skipped": _skip.code,
                "reason": _skip.detail}

    # Andon if the host can't produce the test_env this repo requires.
    # The /investigate skill running without env-awareness produces
    # fixes shaped by wrong assumptions (the wild #1924 class). Halt
    # before the skill runs; operator clears once the env is reachable.
    from sweep.activities.qa import assert_test_env_available
    from sweep import observe
    resolved_env = assert_test_env_available(msg.repo)
    observe.event("investigate_env_check", repo=msg.repo, issue=msg.pr,
                  test_env=resolved_env)

    try:
        return await _investigate_cycle_inner(msg)
    finally:
        # Pull signal: idle-style. Every investigate cycle ends with a
        # rope tug; rope reads roll.jsonl depth and decides whether to
        # fire. Investigate is one of the actors most likely to drain
        # work (long cycles, fewer outputs per input), so its idle is a
        # high-value signal for the controller.
        try:
            from sweep.activities.rope import kick_rope_card
            await kick_rope_card("investigate", incoming=msg)
        except Exception as e:
            from sweep import observe
            observe.event("kick_rope_failed", site="investigate_cycle",
                          error_type=type(e).__name__, error=str(e)[:200])


async def _kick_human_decision(repo: str, pr: int, *,
                               signal: str, summary: str,
                               artifact_path: str) -> str | None:
    """Punt-to-inbox: skill ran, applied its go-with-the-flow heuristic,
    couldn't pick — operator gets the artifact in their inbox to
    decide. Last resort, AFTER the skill has already tried. The card
    carries enough context (hygraph path + summary line) for the
    operator to open the artifact and pick.

    Routes to the human bucket via the standard router shape; human
    is view-only, so the jsonl write IS the surface (cockpit's 📥
    chip + `sweep inbox actor human`)."""
    import datetime as _dt
    import json as _json
    from dataclasses import asdict as _asdict
    from pathlib import Path
    from sweep.types import Message
    from sweep.activities.pr_state import _signal_actor

    ts = _dt.datetime.now(_dt.timezone.utc)
    slug = repo.replace("/", "-")
    msg_id = f"investigate-decision-{slug}-{pr}-{signal}"
    msg = Message(
        msg_id=msg_id,
        sender="investigate",
        intent="decide",
        repo=repo,
        pr=pr,
        branch=None,
        payload={
            "signal": signal,
            "summary": summary,
            "artifact_path": artifact_path,
            # Reason is signal-specific: "unclassified" means the
            # pattern-matcher didn't recognize the artifact's halt
            # vocabulary; anything else means the skill itself
            # reached a decision point that requires operator input.
            "reason": (
                "classifier matched no termination signal in artifact"
                if signal == "unclassified"
                else f"skill halted at decision point ({signal})"
            ),
        },
        ts=ts.isoformat(),
    )
    inbox = Path.home() / ".sweep" / "inbox" / "human.jsonl"
    inbox.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(inbox, "a") as f:
            f.write(_json.dumps(_asdict(msg)) + "\n")
    except Exception as e:
        from sweep import observe
        observe.event("human_decision_card_write_failed",
                      repo=repo, pr=pr,
                      error_type=type(e).__name__, error=str(e)[:200])
        return None
    from sweep import observe
    observe.event("human_decision_card_deposited",
                  repo=repo, pr=pr,
                  signal=signal, summary=summary[:200])
    return await _signal_actor("human", msg)


async def _investigate_cycle_inner(msg: Message) -> dict:
    ref = f"{msg.repo}#{msg.pr}"
    from sweep import budget as _budget, observe, skill_result
    # Honor the caller's budget key: reinvestigate_cycle sets caller
    # to "reinvestigate" before delegating; production-lane callers
    # leave it as "investigate" (default). Without this both lanes
    # share the investigate budget and one floods the other.
    caller = _budget.current_caller()
    if caller not in _budget.SUBPROCESS_ESTIMATE:
        caller = "investigate"
    _budget.record_subprocess_estimate(caller)

    # Note the artifact's mtime BEFORE running so we can detect a
    # fresh write vs an old file. Artifact path convention:
    # `repo-hypotheses/<owner>__<repo>__<issue>.md` (per-issue).
    artifact = _investigate_artifact_path(msg.repo, msg.pr)
    before_mtime = artifact.stat().st_mtime if artifact.exists() else 0.0

    # Runner choice is data-driven: whichever model is configured for the
    # `investigate_primary` role decides which CLI executes the skill.
    # Default is codex (set in models.py); override via
    # SWEEP_MODEL_INVESTIGATE_PRIMARY=opus to swap back to claude.
    from sweep import models as _models
    primary = _models.default_for("investigate_primary")
    runner = "codex" if primary.provider == "openai" else "claude"

    # Pre-fetch the gh context pack so the skill doesn't have to do its
    # own gh issue/PR lookups. Two pack shapes by caller:
    #
    #   investigate (production lane): issue + related PRs + self-history
    #     + CI status. The "investigate a bug report" frame.
    #   reinvestigate (engagement lane): PR header + failing-check rollup
    #     + per-job log tails + recent commits + recent comments. The
    #     "PR's CI went red, look at the failure" frame.
    #
    # Both write to INVESTIGATE_CONTEXT so the skill markdown reads one
    # env var. The pack content tells the skill which mode it's in.
    extra_env: dict[str, str] = {}
    try:
        if caller == "reinvestigate":
            from sweep.activities.reinvestigate_prep import write_reinvestigate_context_pack
            ctx_path = write_reinvestigate_context_pack(
                msg.repo, int(msg.pr), msg.msg_id)
            pack_kind = "reinvestigate"
        else:
            from sweep.activities.investigate_prep import write_context_pack
            ctx_path = write_context_pack(msg.repo, int(msg.pr), msg.msg_id)
            pack_kind = "investigate"
        extra_env["INVESTIGATE_CONTEXT"] = str(ctx_path)
        observe.event("investigate_context_packed", repo=msg.repo,
                      issue=msg.pr, ctx_path=str(ctx_path),
                      ctx_bytes=ctx_path.stat().st_size,
                      pack_kind=pack_kind)
    except Exception as e:
        observe.event("investigate_context_pack_failed", repo=msg.repo,
                      issue=msg.pr, error_type=type(e).__name__,
                      error=str(e)[:200])

    result = await _run_skill(["/investigate", ref], label="investigate",
                              timeout_s=1800, runner=runner,
                              extra_env=extra_env)

    # Artifact-first: /investigate's canonical contract is the
    # hypothesis graph file. When it exists, read it and classify
    # the halt section — the artifact already names its conclusion
    # (verdict, decision, halt reason, awaiting-gate). Beats both
    # the old "mtime advanced ⇒ produced_pr" reflex (wrong: most
    # halts don't ship) and a Sonnet shim call (slower, lossy).
    after_mtime = artifact.stat().st_mtime if artifact.exists() else 0.0
    artifact_fresh = after_mtime > before_mtime
    if artifact.exists():
        # Investigate's responsibility ends at producing the artifact.
        # Production lane → switch classifies + routes (qa/comment-issue/
        # human). Engagement lane (reinvestigate) bypasses switch: switch's
        # vocabulary is shaped for new-PR decisions, and a proposed-fix on
        # an existing PR has no signal that fits — it ends up "human-gated"
        # by exclusion (witnessed: wiiznokes/fan-control#247). Reinvestigate
        # kicks reqa itself after this returns; production-lane filtering
        # is the trust anchor.
        is_reinvestigate = _budget.current_caller() == "reinvestigate"
        observe.event(
            "investigate_done", repo=msg.repo, issue=msg.pr,
            rc=result.get("rc", 0),
            artifact_path=str(artifact),
            artifact_fresh=artifact_fresh,
            summary=(
                "(reinvestigate → reqa, switch bypassed)"
                if is_reinvestigate
                else "(handed to switch for classification + routing)"
            ),
        )
        if not is_reinvestigate:
            try:
                from sweep.activities.switch import kick_switch_card
                await kick_switch_card(
                    msg.repo, int(msg.pr),
                    artifact_path=str(artifact),
                    source="investigate",
                    incoming=msg,
                )
            except Exception as e:
                observe.event("kick_switch_failed",
                              repo=msg.repo, issue=msg.pr,
                              error_type=type(e).__name__, error=str(e)[:200])
        # Surface artifact freshness on the result so reinvestigate_cycle
        # can gate its own reqa kick. _run_skill's dict otherwise drops
        # this signal.
        result["artifact_fresh"] = artifact_fresh
        result["artifact_path"] = str(artifact)
        # Parallel side-hatch: if the artifact mentions a *separate* bug
        # worth filing, kick file-issue too. Independent of switch's
        # primary verdict — a shipped fix can still surface a side-bug.
        try:
            if _has_separate_bug_signal(artifact):
                from sweep.activities.file_issue import kick_file_issue_card
                await kick_file_issue_card(
                    msg.repo, int(msg.pr),
                    source="investigate",
                    signal="separate_bug_found",
                    incoming=msg,
                )
        except Exception as e:
            observe.event("kick_file_issue_failed",
                          repo=msg.repo, issue=msg.pr,
                          error_type=type(e).__name__, error=str(e)[:200])
        return result

    # Artifact missing — degraded mode. Try the shim on stdout.
    parsed = skill_result.shim("investigate", result.get("stdout_tail", ""))
    if skill_result.is_rejected(parsed):
        skill_result.record_rejection("investigate", msg.__dict__, parsed)
        # Side-hatch: a self-PR halt rejection often has comment-issue value
        # ("noticed you're on it, leaving you to it"). Route it to
        # comment-issue with the rejection reason as the signal. If no
        # artifact ever got written, comment-issue's artifact_missing screen
        # drops the card — only artifact-bearing rejections produce
        # drafts. Filter to self-PR halts only; broader policy-gate
        # rejections (kill list, AI hostile) aren't comment-issue-worthy.
        reason = str(parsed.get("reject_reason") or "")
        if "self-pr" in reason.lower() or "self pr" in reason.lower() \
                or "maintainer self-pr halt" in reason.lower():
            from sweep.activities.comment_issue import kick_comment_issue_card
            try:
                await kick_comment_issue_card(
                    msg.repo, int(msg.pr),
                    source="investigate-reject",
                    signal="self-pr-halt",
                    incoming=msg,
                )
            except Exception as e:
                observe.event("kick_comment_issue_failed",
                              site="investigate_reject",
                              repo=msg.repo, issue=msg.pr,
                              error_type=type(e).__name__,
                              error=str(e)[:200])
        return result
    if parsed:
        summary = "shim-fallback: " + str(parsed.get("summary", ""))[:180]
        observe.event(
            "investigate_done", repo=msg.repo, issue=msg.pr,
            rc=result.get("rc", 0),
            produced_pr=bool(parsed.get("produced_pr")),
            no_fix=bool(parsed.get("no_fix")),
            summary=summary,
        )
        # Route — never silent return. If no specific bucket matched,
        # send to human so the operator sees the artifact gap.
        await _route_or_human(msg, parsed, summary,
                              artifact_path=str(artifact))
        return result
    # Last-ditch heuristic so the funnel still shows *something*.
    tail = (result.get("stdout_tail") or "").lower()
    produced_pr = ("pull/" in tail or "opened pr" in tail
                   or "pushed branch" in tail or "drip-ready" in tail)
    no_fix = ("no fix" in tail or "blocked" in tail or "skip" in tail
              or "no actionable" in tail)
    summary = "(heuristic-fallback, no artifact and no shim parse)"
    observe.event(
        "investigate_done", repo=msg.repo, issue=msg.pr,
        rc=result.get("rc", 0), produced_pr=produced_pr, no_fix=no_fix,
        summary=summary,
    )
    await _route_or_human(
        msg, {"produced_pr": produced_pr, "no_fix": no_fix}, summary,
        artifact_path=str(artifact),
    )
    return result


async def _route_or_human(msg, verdict: dict, summary: str,
                          artifact_path: str) -> None:
    """Catch-all router for the shim/heuristic paths. Kicks comment-issue
    for no-fix verdicts; otherwise falls through to human inbox so the
    operator sees the case. Never silent return.

    Operator contract: every investigation routes to exactly one of
    {qa, comment-issue, human}. The qa path requires a real fix branch,
    which the shim path can't construct; so shim outcomes route only to
    comment-issue (no-fix) or human (everything else)."""
    try:
        if verdict.get("no_fix"):
            from sweep.activities.comment_issue import kick_comment_issue_card
            await kick_comment_issue_card(
                msg.repo, int(msg.pr),
                source="investigate-shim",
                signal="no-fix",
                incoming=msg,
            )
            return
        await _kick_human_decision(
            msg.repo, msg.pr,
            signal="shim-uncategorized",
            summary=summary,
            artifact_path=artifact_path,
        )
    except Exception as e:
        observe.event("route_or_human_failed",
                      repo=msg.repo, issue=msg.pr,
                      error_type=type(e).__name__, error=str(e)[:200])


def _investigate_artifact_path(repo: str, issue: int):
    """Per-issue hypothesis graph: prefer the new
    repo-hypotheses/<owner>__<repo>__<issue>.md convention. Falls
    back to the old <owner>-<repo>.md (per-repo, no issue suffix)
    when the new file doesn't yet exist but the old one does — the
    wild-linker/wild#1924 case where reinvestigate's classifier
    couldn't find its own artifact because the file was at the old
    path. New writes always go to the new convention; this just
    keeps the read side from missing legacy files."""
    from pathlib import Path
    root = Path("/Users/junekim/Documents/sweep/repo-hypotheses")
    new = root / f"{repo.replace('/', '__')}__{issue}.md"
    if new.exists():
        return new
    old = root / f"{repo.replace('/', '-')}.md"
    if old.exists():
        return old
    return new  # new path is the canonical destination for writes


# ---------------------------------------------------------------- triage host-compat
#
# Keywords in the issue's title or labels that indicate the bug needs an
# environment our linux-docker substrate can't reproduce in. When any
# match, triage evicts the repo (not just the issue) — one such issue
# per repo is enough signal that the project has a dimension we can't
# support; better to stop paying tokens on candidates that will fail at
# the test-env gate anyway.
#
# Conservative list. False positives mean we evict a repo unnecessarily;
# operator can pull entries out of ~/.sweep/control/sift_evicted.txt by
# hand. Prefer specific platform/vendor terms over generic ones like
# "gpu" (which appears in unrelated discussion in many repos).
_HOST_INCOMPAT_TERMS = (
    # GPU compute we don't have
    "cuda", "nvidia driver", "rocm", "amd gpu", "tensorrt",
    "compute shader", "gpgpu",
    # Windows-only stacks
    "windows-only", "winapi", "win32 api", "wdk", "windows kernel",
    "wpf", "winforms", "directx", "direct3d", "uwp", "winui",
    ".net framework", "wsl-only",
    # macOS/iOS bundles
    "metal api", "uikit", "appkit", "xcode required", "ios-only",
    # Kernel / drivers
    "kernel module", "ebpf program", "out-of-tree driver",
)


def _host_incompat_signal(title: str, labels: list) -> str | None:
    """Return a one-line reason if the issue's title or labels indicate
    we can't reproduce in our env. Otherwise None.

    `labels` is the gh shape: list of {"name": str, ...} OR list of
    str — both accepted. Conservative substring scan; we'd rather
    miss a repo than evict the wrong one (operator can re-add)."""
    haystack = (title or "").lower()
    for lab in labels or []:
        name = lab.get("name") if isinstance(lab, dict) else str(lab)
        if name:
            haystack += " " + str(name).lower()
    for term in _HOST_INCOMPAT_TERMS:
        if term in haystack:
            return f"host-incompat: {term!r} in issue title/labels"
    return None


_EVICTED_PATH = Path.home() / ".sweep" / "control" / "sift_evicted.txt"
_COLLAB_SHAPE_CACHE = Path.home() / ".sweep" / "control" / "repo_collab_shape.json"


def _outside_pr_hostility_check(repo: str) -> str | None:
    """Cheap per-repo signal for 'product-shaped, outside-PR hostile'.

    Two combined cues, both witnessed on pingcap/ossinsight:
      1) Top-4 contributor concentration ≥ 80% AND ≤ 15 real (>10-commit,
         non-bot) contributors — a small internal team, not a community.
      2) Forks-per-real-contributor ≥ 30 — GitHub used as distribution
         (people clone to self-host) rather than collaboration.
    Either alone is enough; both together is the textbook shape.

    Returns a reason string if hostile, else None. Cached per repo —
    one gh api round-trip per repo lifetime, not per issue.
    """
    import json as _json
    try:
        cache: dict = (
            _json.loads(_COLLAB_SHAPE_CACHE.read_text())
            if _COLLAB_SHAPE_CACHE.exists() else {}
        )
    except (OSError, _json.JSONDecodeError):
        cache = {}
    if repo in cache:
        entry = cache[repo]
        return entry.get("reason") or None  # None means "checked, fine"

    try:
        from sweep import gh_io
        meta = gh_io.api(f"repos/{repo}", ttl=24 * 3600)
        forks = int(meta.get("forks_count") or 0) if isinstance(meta, dict) else 0
        contribs = gh_io.api(
            f"repos/{repo}/contributors?per_page=100", ttl=24 * 3600,
        )
        if not isinstance(contribs, list):
            contribs = []
    except Exception:
        return None  # fail-soft; never block triage on this gate
    # If we hit the page cap, real contributor count is unknown — can't
    # trust the forks-per-contrib ratio. Top-4-share is still valid
    # because saturated lists have small top-4 fractions anyway.
    contrib_count_saturated = len(contribs) >= 100
    real = [
        c for c in contribs
        if isinstance(c, dict)
        and not (c.get("login") or "").endswith("[bot]")
        and int(c.get("contributions", 0)) >= 10
    ]
    if not real:
        return None
    top4 = sum(int(c.get("contributions", 0)) for c in real[:4])
    total = sum(int(c.get("contributions", 0)) for c in real)
    top4_share = (top4 / total) if total else 0.0
    forks_per_contrib = (forks / len(real)) if real else 0.0

    reason: str | None = None
    if top4_share >= 0.80 and len(real) <= 15:
        reason = (
            f"product-shaped: top-4 {top4_share:.0%} of commits, "
            f"{len(real)} real contributors — small internal team"
        )
    elif forks_per_contrib >= 30 and not contrib_count_saturated:
        reason = (
            f"distribution-shaped: {forks} forks / {len(real)} contributors "
            f"= {forks_per_contrib:.0f}:1 — clone-to-self-host, not collab"
        )

    cache[repo] = {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "forks": forks,
        "real_contributors": len(real),
        "top4_share": round(top4_share, 3),
        "forks_per_contrib": round(forks_per_contrib, 1),
        "reason": reason,
    }
    try:
        _COLLAB_SHAPE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _COLLAB_SHAPE_CACHE.write_text(_json.dumps(cache, indent=2))
    except OSError:
        pass
    return reason


def _evict_repo(repo: str, reason: str) -> None:
    """Append to the evicted-repos file. Same path sift uses for
    auto-eviction. Idempotent at read time (fnmatch dedup), and a
    no-op if the repo is already listed."""
    try:
        if _EVICTED_PATH.exists():
            for line in _EVICTED_PATH.read_text().splitlines():
                pat = line.split("#", 1)[0].strip().lower()
                if pat == repo.lower():
                    return  # already evicted
    except OSError:
        pass
    _EVICTED_PATH.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with _EVICTED_PATH.open("a") as f:
        f.write(f"{repo}  # auto-evicted {ts} ({reason})\n")
    observe.event("repo_evicted", repo=repo, reason=reason, source="triage")


# Phrases that suggest the investigation found a *separate* bug worth
# filing — discovered during the work but not the issue under
# investigation. The /file-issue skill is the actual decider (it reads
# the artifact and judges concreteness); this cheap pattern-match is
# just the trigger. False positives are fine — skill SKIPs them.
_SEPARATE_BUG_PHRASES = (
    "separate issue", "separately filed", "warrants its own issue",
    "should be reported separately", "should be filed separately",
    "open a new issue", "a new issue for", "needs its own issue",
    "unrelated bug", "unrelated regression", "adjacent bug",
    "side-bug", "side bug", "secondary bug",
    "also noticed", "also found", "also discovered",
    "noticed adjacent", "in addition there is a bug",
)


def _has_separate_bug_signal(path) -> bool:
    """Cheap substring scan over the artifact tail. Returns True if
    any pattern in _SEPARATE_BUG_PHRASES appears. False on read error
    or empty file — file actor is opt-in by signal, no signal = no fire."""
    try:
        text = path.read_text()
    except OSError:
        return False
    if not text.strip():
        return False
    tail = text[-6000:].lower()
    return any(p in tail for p in _SEPARATE_BUG_PHRASES)

