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
import json
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
    env = os.environ.copy()
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
    from sweep import observe, gh_io
    from sweep import budget as _budget
    from sweep.activities.scout import kick_scout_card
    _budget.record_subprocess_estimate("triage")
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
        # Pull signal: route through rope (the depth controller) instead
        # of kicking scout directly. Rope reads scout.jsonl depth and
        # decides whether to fire; one idle signal in, zero-or-one scout
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
    if not msg.repo or not msg.pr:
        raise ApplicationError("investigate: repo + issue required",
                               non_retryable=True)

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
        # rope tug; rope reads scout.jsonl depth and decides whether to
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
            "reason": "skill's go-with-the-flow heuristic couldn't pick",
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
    # own gh issue/PR lookups. Reduces the gh-call budget the skill
    # consumes (those calls were invisible to per-actor accounting),
    # makes context deterministic across runs, and shaves tool-use
    # round-trips. See sweep/activities/investigate_prep.py for what's
    # in the pack and what's deliberately left for the skill to fetch.
    extra_env: dict[str, str] = {}
    try:
        from sweep.activities.investigate_prep import write_context_pack
        ctx_path = write_context_pack(msg.repo, int(msg.pr), msg.msg_id)
        extra_env["INVESTIGATE_CONTEXT"] = str(ctx_path)
        observe.event("investigate_context_packed", repo=msg.repo,
                      issue=msg.pr, ctx_path=str(ctx_path),
                      ctx_bytes=ctx_path.stat().st_size)
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
            # pattern as [[O1]]: the wrapper decides, not the skill.
            if classified["no_fix"] and classified.get("summary"):
                from sweep.activities.tissue import kick_tissue_card
                try:
                    await kick_tissue_card(
                        msg.repo, int(msg.pr),
                        source="investigate",
                        signal=classified["signal"],
                        incoming=msg,
                    )
                except Exception as e:
                    observe.event("kick_tissue_failed",
                                  repo=msg.repo, issue=msg.pr,
                                  error_type=type(e).__name__,
                                  error=str(e)[:200])

            # Production-lane handoff: if the investigation produced
            # a fresh fix branch, kick qa-actor for verification before
            # the push. Branch derived from the substrate's worktree
            # (the dir investigate's /investigate skill operates in
            # by convention). qa-actor will run test_attestation, write
            # the attestation files to <worktree>/attestations/<slug>,
            # then kick compose. submit-actor's _attestation_gate is
            # the structural backstop that refuses push without a
            # verified manifest.
            if classified["produced_pr"] and not classified["human_gated"]:
                try:
                    from sweep.activities.worktree import _safe_dir
                    import subprocess
                    wt = _safe_dir(msg.repo)
                    if wt.exists():
                        br_out = subprocess.run(
                            ["git", "-C", str(wt), "rev-parse",
                             "--abbrev-ref", "HEAD"],
                            capture_output=True, text=True, timeout=5,
                        )
                        branch = br_out.stdout.strip() if br_out.returncode == 0 else ""
                        if not branch or branch in ("HEAD", "main", "master"):
                            observe.event("kick_qa_skipped",
                                          repo=msg.repo, issue=msg.pr,
                                          reason=f"branch={branch!r} not a fix branch")
                        else:
                            # [[O1]] sanity check: skill SAID it shipped; verify
                            # the branch actually exists on the remote before
                            # we wake qa to chase a phantom. Otherwise qa
                            # tries to checkout a branch that origin doesn't
                            # have and errors out, which masquerades as a
                            # toolchain bug rather than a skill misreport.
                            ls = subprocess.run(
                                ["git", "-C", str(wt), "ls-remote",
                                 "--heads", "origin", branch],
                                capture_output=True, text=True, timeout=10,
                            )
                            if ls.returncode == 0 and ls.stdout.strip():
                                # Route to qa first (adversarial review,
                                # may edit the branch), then qa forwards
                                # to attest for the test gate, then attest
                                # forwards to compose for the PR body.
                                # Previous shape (investigate → attest → qa)
                                # double-attested because qa_actor still
                                # ran test_attestation internally.
                                from sweep.activities.qa import kick_qa_card
                                await kick_qa_card(
                                    msg.repo, branch,
                                    sender="investigate",
                                    incoming=msg,
                                )
                            else:
                                observe.event("ghost_branch",
                                              repo=msg.repo, issue=msg.pr,
                                              branch=branch,
                                              reason="skill claimed shipped; "
                                                     "ls-remote shows branch not "
                                                     "on origin")
                except Exception as e:
                    observe.event("kick_qa_failed",
                                  repo=msg.repo, issue=msg.pr,
                                  error_type=type(e).__name__,
                                  error=str(e)[:200])

            # Ambiguous case: skill ran, classifier returned a signal
            # but none of the routing branches matched (not no-fix, not
            # produced-pr, not human-gated — e.g. "three options,
            # awaiting choice" shape). The substrate's rule: when in
            # doubt, route to operator inbox so the work is visible.
            # Punt-to-inbox is the andon for skill-side ambiguity.
            if (not classified["produced_pr"]
                    and not classified["no_fix"]
                    and not classified["human_gated"]
                    and classified.get("summary")):
                try:
                    await _kick_human_decision(
                        msg.repo, msg.pr,
                        signal=classified["signal"],
                        summary=classified["summary"],
                        artifact_path=str(artifact),
                    )
                except Exception as e:
                    observe.event("kick_human_failed",
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
                    incoming=msg,
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
