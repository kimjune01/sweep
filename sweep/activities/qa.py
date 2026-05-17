"""QA activities — single-entry, structurally bounded.

The activity signature *is* the WIP=1 enforcer. You cannot call qa_one_entry
with multiple repos or branches.
"""

from __future__ import annotations

import asyncio
import re
import shlex
import subprocess
import time
from pathlib import Path

from temporalio import activity
from temporalio.exceptions import ApplicationError

from sweep import control_state, llm_io, models, observe, retro_params, retro_state
from sweep.io_safe import atomic_write_text
from sweep.types import GateAttestation, QaOneEntryRequest, QaOneEntryResult


def assert_test_env_available(repo: str) -> str:
    """Pre-flight check: can the host actually produce the test env
    this repo requires? Returns the resolved test_env (for the caller's
    logs). Raises ApplicationError(non_retryable=True) — which trips
    the actor's andon — when the env is declared but unreachable.

    The point is to fail loud BEFORE running the skill against a
    platform we can't validate on. A skill that runs without env
    awareness produces fixes shaped by wrong assumptions; the right
    move is to halt the line and let the operator install docker /
    pull the image / fix the env config, then `sweep andon clear`.
    """
    env, _ = _get_test_env(repo)
    if env == "native":
        return env
    if env.startswith("docker:"):
        image = env.removeprefix("docker:")
        # Docker daemon reachable?
        info = subprocess.run(
            ["docker", "info"],
            capture_output=True, text=True, timeout=10,
        )
        if info.returncode != 0:
            raise ApplicationError(
                f"test_env={env!r} requires docker but `docker info` "
                f"failed (rc={info.returncode}): {(info.stderr or '')[:200]}. "
                f"Either install/start docker (env-setup path), OR "
                f"tighten sift's filter so {repo} isn't investigated "
                f"on this host. Then `sweep andon clear`.",
                non_retryable=True,
            )
        # Image pullable / present? Pull is idempotent (no-op if cached).
        pull = subprocess.run(
            ["docker", "pull", "--quiet", image],
            capture_output=True, text=True, timeout=120,
        )
        if pull.returncode != 0:
            raise ApplicationError(
                f"test_env={env!r} requires image {image!r} but "
                f"`docker pull` failed (rc={pull.returncode}): "
                f"{(pull.stderr or '')[:200]}. Either fix the image "
                f"name in retro_params (env-setup path), OR tighten "
                f"sift's filter so {repo} isn't investigated. Then "
                f"`sweep andon clear`.",
                non_retryable=True,
            )
        return env
    raise ApplicationError(
        f"unknown test_env {env!r}; expected 'native' or 'docker:<image>'",
        non_retryable=True,
    )


def _get_test_env(repo: str) -> tuple[str, str | None]:
    """Resolve (test_env, setup_cmd) for a repo from retro_params.

    test_env: "native" (default) or "docker:<image>" (e.g.
              "docker:rust:1.94" for wild-class repos).
    setup_cmd: shell command run inside the container BEFORE test_cmd
               (e.g. "apt-get update && apt-get install -y clang lld").
               None for native or when no setup needed.

    Operators set these per repo via `sweep retro set <repo> test_env
    docker:rust:1.94 --reason 'needs Linux+clang+lld'`. Future:
    auto-infer from .github/workflows/ + Dockerfile."""
    params = retro_params.resolved(repo)
    return (
        params.get("test_env", "native"),
        params.get("test_setup_cmd"),
    )


async def _run_in_test_env(
    test_cmd: str, *, worktree: str, test_env: str, setup_cmd: str | None,
) -> subprocess.CompletedProcess:
    """Run test_cmd in the right environment. Native = host shell;
    docker:<image> = container with worktree mounted at /work and a
    persistent build cache mounted at /cache (CARGO_TARGET_DIR points
    at it). Cache is per-repo under ~/.sweep/build-cache/<owner__repo>
    so successive runs amortize compile cost.

    The setup_cmd runs once inside the container per invocation
    (cheap apt-get installs are mostly cached; first run is slow).
    No persistent setup-installed-state — we trade speed for
    determinism."""
    if test_env == "native":
        return await asyncio.to_thread(
            subprocess.run, shlex.split(test_cmd),
            cwd=worktree, capture_output=True, text=True,
        )
    if not test_env.startswith("docker:"):
        raise ApplicationError(
            f"unknown test_env {test_env!r}; expected 'native' or 'docker:<image>'",
            non_retryable=True,
        )
    image = test_env.removeprefix("docker:")
    cache_dir = Path.home() / ".sweep" / "build-cache" / Path(worktree).name
    cache_dir.mkdir(parents=True, exist_ok=True)
    inner = f"{setup_cmd} && {test_cmd}" if setup_cmd else test_cmd
    docker_args = [
        "docker", "run", "--rm",
        "-v", f"{worktree}:/work", "-w", "/work",
        "-v", f"{cache_dir}:/cache",
        "-e", "CARGO_TARGET_DIR=/cache",
        image, "bash", "-c", inner,
    ]
    return await asyncio.to_thread(
        subprocess.run, docker_args, capture_output=True, text=True,
    )

# adversary_1 / _2 / _3 cascade (defaults: codex → gemini → opus).
# Each reviewer activity reads its slot from models.default_for.
ADVERSARY_1 = models.default_for("adversary_1")  # codex
ADVERSARY_2 = models.default_for("adversary_2")  # gemini
ADVERSARY_3 = models.default_for("adversary_3")  # opus subagent fallback
CODE_MODEL  = models.default_for("code")          # opus, for impl/fix tasks

ATTESTATIONS = Path.home() / ".sweep" / "attestations"
QA_INBOX = Path.home() / ".sweep" / "inbox" / "qa.jsonl"


@activity.defn
async def kick_qa_card(repo: str, branch: str,
                       pr: int | None = None,
                       sender: str = "investigate",
                       attestation_hash: str | None = None) -> str | None:
    """Deposit a card on qa.jsonl and signal qa-actor. Called by
    investigate_cycle on the production lane when a fresh fix branch
    is ready for verification. Reqa-actor handles the engagement-lane
    equivalent via kick_reqa_card."""
    import datetime as _dt
    import json as _json
    from dataclasses import asdict as _asdict
    from sweep.types import Message
    from sweep.activities.pr_state import _signal_actor

    ts = _dt.datetime.now(_dt.timezone.utc)
    slug = repo.replace("/", "-")
    pr_part = pr if pr is not None else "new"
    msg_id = f"qa-{ts.strftime('%Y%m%dT%H%M%S')}-{slug}-{pr_part}"
    payload: dict = {}
    if attestation_hash:
        payload["attestation_hash"] = attestation_hash
    msg = Message(
        msg_id=msg_id,
        sender=sender,
        intent="reattest",
        repo=repo,
        pr=pr,
        branch=branch,
        payload=payload,
        ts=ts.isoformat(),
    )
    QA_INBOX.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(QA_INBOX, "a") as f:
            f.write(_json.dumps(_asdict(msg)) + "\n")
    except Exception as e:
        observe.event("qa_card_write_failed", repo=repo, branch=branch,
                      error_type=type(e).__name__, error=str(e)[:200])
        return None
    observe.event("qa_card_deposited", repo=repo, branch=branch,
                  pr=pr, sender=sender, msg_id=msg_id)
    return await _signal_actor("qa", msg)


def _heartbeat(details: dict) -> None:
    """Heartbeat from inside an activity context, no-op outside.

    qa_one_entry is callable as a plain coroutine (terminal-mode + e2e
    scripts) where there is no activity context — but the sub-activities
    it composes still call activity.heartbeat. Swallow the resulting
    RuntimeError so the convenience composer keeps working from scripts.

    Scope is deliberately narrow: only RuntimeError is caught. Temporal's
    cancellation signal is CancelledError (subclass of FailureError, not
    RuntimeError), so a cancelled activity still aborts cleanly — the
    runtime must see the cancel.
    """
    try:
        activity.heartbeat(details)
    except RuntimeError:
        pass


def _head_sha(worktree: str) -> str:
    """Capture the current HEAD SHA of the worktree. Pins fuses to this code."""
    out = subprocess.run(
        ["git", "-C", worktree, "rev-parse", "HEAD"],
        capture_output=True, text=True, check=False,
    )
    return out.stdout.strip()


def _capture(msg_id: str, name: str, content: str, *,
             worktree: str | None = None) -> GateAttestation:
    """Write the reviewer response to a deterministic path, return its receipt.

    The activity that did the call is the only thing that ever writes here.
    A downstream consumer cannot fabricate this — it can only point at the
    bytes that already exist on disk. Atomic write closes the partial-write
    crash window.

    If `worktree` is provided, pin the attestation to its current HEAD SHA.
    This is the event-driven fuse: the attestation is valid as long as the
    PR head matches; the moment a new commit lands the fuse blows.
    """
    p = ATTESTATIONS / msg_id / f"{name}.txt"
    sha = atomic_write_text(p, content)
    return GateAttestation(
        verdict="pass",  # caller overrides after parsing
        artifact_path=str(p),
        sha256=sha,
        verbatim_excerpt=content[:200],
        pinned_head_sha=_head_sha(worktree) if worktree else None,
    )


@activity.defn
async def test_attestation(req: QaOneEntryRequest) -> GateAttestation:
    """Run test_cmd on master (must fail) and on fix branch (must pass)."""
    if not req.msg_id:
        raise ApplicationError("msg_id required", non_retryable=True)
    if "/" not in req.repo:
        raise ApplicationError("repo must be owner/repo", non_retryable=True)
    if not req.branch:
        raise ApplicationError("branch required", non_retryable=True)

    worktree = req.worktree
    log: list[str] = []
    _test_start = time.time()
    test_env, setup_cmd = _get_test_env(req.repo)

    async def _run(args: list[str]) -> subprocess.CompletedProcess:
        if not args or not args[0]:
            # Empty/blank command — caller misconfigured. Halt-worthy
            # because qa shouldn't guess at empty inputs.
            raise ApplicationError(
                "test_cmd resolved to empty argv", non_retryable=True,
            )
        try:
            # to_thread keeps the worker's asyncio loop free during
            # long test-suite runs; otherwise polling stalls and
            # Temporal sees the worker as gone.
            return await asyncio.to_thread(
                subprocess.run, args, cwd=worktree, capture_output=True, text=True,
            )
        except FileNotFoundError as e:
            # Toolchain missing on this machine (cargo, go, npm, etc.).
            # Don't halt the whole actor — just skip this PR with a
            # marker the workflow recognizes and moves past.
            raise ApplicationError(
                f"skip: toolchain not installed ({args[0]!r}); {e}",
                non_retryable=True,
            )

    # Restore tracked files to their indexed state before swapping branches.
    # A dirty worktree (modified tracked files from an aborted prior run)
    # would otherwise make the next `git checkout default` fail with a
    # conflict — caught by master_co below, but the blame would be wrong.
    # `git checkout HEAD -- .` is the in-place restore; bare `git checkout
    # HEAD` only confirms the current commit and leaves modifications.
    head_co = await _run(["git", "checkout", "--quiet", "HEAD", "--", "."])
    if head_co.returncode != 0:
        raise ApplicationError(
            f"git checkout HEAD -- . failed (rc={head_co.returncode}): "
            f"{(head_co.stderr or '')[:300]}",
            non_retryable=True,
        )
    default = (await _run(["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"])).stdout.strip()
    default = default.split("/", 1)[1] if "/" in default else "main"

    _heartbeat({"stage": "checkout_master"})
    master_co = await _run(["git", "checkout", "--quiet", default])
    if master_co.returncode != 0:
        raise ApplicationError(
            f"git checkout {default} failed (rc={master_co.returncode}): "
            f"{(master_co.stderr or '')[:300]}",
            non_retryable=True,
        )
    _heartbeat({"stage": "test_on_master"})
    master_run = await _run_in_test_env(
        req.test_cmd, worktree=worktree, test_env=test_env, setup_cmd=setup_cmd,
    )
    log.append(f"master ({default}) exit={master_run.returncode} env={test_env}")
    if master_run.returncode == 0:
        raise ApplicationError(
            "test_passes_on_master — bug fixed upstream or test wrong",
            non_retryable=True,
        )

    _heartbeat({"stage": "checkout_fix"})
    fix_co = await _run(["git", "checkout", "--quiet", req.branch])
    if fix_co.returncode != 0:
        raise ApplicationError(
            f"git checkout {req.branch} failed (rc={fix_co.returncode}): "
            f"{(fix_co.stderr or '')[:300]}",
            non_retryable=True,
        )
    _heartbeat({"stage": "test_on_fix"})
    fix_run = await _run_in_test_env(
        req.test_cmd, worktree=worktree, test_env=test_env, setup_cmd=setup_cmd,
    )
    log.append(f"fix ({req.branch}) exit={fix_run.returncode} env={test_env}")
    if fix_run.returncode != 0:
        raise ApplicationError(
            f"test_fails_on_fix — fix is broken: {fix_run.stderr[:500]}",
            non_retryable=True,
        )

    body = "\n".join(log) + "\n\n--- master stderr ---\n" + master_run.stderr + "\n--- fix stdout ---\n" + fix_run.stdout
    att = _capture(req.msg_id, "test", body, worktree=req.worktree)
    att.verdict = "pass"

    # Write the committable attestation set into the worktree's
    # attestations/ dir. The "fail on master, pass with fix"
    # discipline is made visible: maintainer can re-run test_cmd
    # on both refs and compare sha256. The deterministic verifier
    # (attestation_verify.py) re-parses after.txt independently —
    # silent-skip cases that this code reads as 'pass' get caught
    # at the push gate.
    try:
        from sweep.attestation_verify import write_attestation_files
        import platform
        # Flat per-repo layout: attestations/<org>-<repo>/issue-<n>-*
        # Maintainer browses attestations/wild-linker-wild/ and sees
        # every issue we've attested as a flat list.
        org_repo = req.repo.replace("/", "-")
        attestation_dir = Path(req.worktree) / "attestations" / org_repo
        issue_key = req.issue or req.branch.removeprefix("fix/").replace("/", "__")
        attestation_name = f"issue-{issue_key}"
        expected_test = req.branch.removeprefix("fix/").replace("/", "__").split("__")[-1].replace("_", "-")
        write_attestation_files(
            attestation_dir,
            attestation_name,
            test_cmd=req.test_cmd,
            expected_test_name=expected_test,
            head_sha=_head_sha(req.worktree),
            host=f"{platform.system().lower()}-{platform.machine()}",
            test_env=test_env,
            before_stdout=(master_run.stdout or "") + "\n--- stderr ---\n" + (master_run.stderr or ""),
            after_stdout=(fix_run.stdout or "") + "\n--- stderr ---\n" + (fix_run.stderr or ""),
            elapsed_seconds=time.time() - _test_start,
        )
        # Auto-commit + ship: the forcing function only works if the
        # files are public. /drip's push picks up the commit naturally.
        # If the verifier rejects, gate_push refuses; if it accepts,
        # the maintainer sees the receipts in the PR. No invisible
        # middle ground where the substrate "checked but didn't show."
        add = subprocess.run(
            ["git", "-C", req.worktree, "add", "attestations/"],
            capture_output=True, text=True, timeout=10,
        )
        if add.returncode == 0:
            cmt = subprocess.run(
                ["git", "-C", req.worktree, "commit", "-m",
                 f"attestation: {slug} ({req.test_cmd[:60]})"],
                capture_output=True, text=True, timeout=10,
            )
            # commit returns 1 when nothing new to commit (re-runs of
            # the same fix on the same sha). That's fine; the existing
            # commit still ships.
            if cmt.returncode == 0:
                observe.event("attestation_committed", msg_id=req.msg_id,
                              slug=slug, branch=req.branch)
    except Exception as e:
        # Don't fail the test_attestation activity if the writer hits
        # an issue (e.g. read-only fs, git config missing) — substrate-
        # private record still got written via _capture above. Log so
        # leakdog can see it; gate_push will then refuse the push for
        # lack of a committed manifest, which is the right outcome.
        observe.event("attestation_write_failed", msg_id=req.msg_id,
                      error_type=type(e).__name__, error=str(e)[:200])

    return att


_REVIEW_SYSTEM = (
    "You are a structural code reviewer. Read the diff and decide whether "
    "the change is sound. Reply with a single verdict line of the form "
    "`verdict: pass`, `verdict: fail`, or `verdict: revise`, followed by a "
    "one-paragraph reason. Keep the reason under 120 words. "
    "If the diff is unreadable, off-topic, or you cannot evaluate it, "
    "output nothing. Empty is a legal answer; do not fabricate a verdict "
    "you don't believe."
)


def _user_prompt(req: QaOneEntryRequest, diff: str) -> str:
    head = f"Repo: {req.repo}\nBranch: {req.branch}"
    if req.issue is not None:
        head += f"\nIssue: #{req.issue}"
    return f"{head}\n\nDiff to review:\n\n{diff}"


def _parse_verdict(response: str) -> str:
    """Pull `verdict: X` (case-insensitive). Default to 'stubbed' for non-Anthropic
    providers whose wrapper is still a stub; treat anything else unparsed as 'revise'
    so the cascade keeps moving rather than auto-passing on garbled output."""
    if response.startswith("<stub:"):
        return "stubbed"
    m = re.search(r"verdict\s*:\s*(pass|fail|revise)", response, re.IGNORECASE)
    if not m:
        return "revise"
    return m.group(1).lower()


@activity.defn
async def codex_review(req: QaOneEntryRequest, diff: str) -> GateAttestation:
    """Adversary_1 review. Codex by default; when the codex CLI isn't
    on PATH (subscription lapsed, machine moved, etc.), falls back to
    claude --print so qa stays on subscription channels and doesn't
    silently bill opus tokens through the API."""
    if not req.msg_id:
        raise ApplicationError("msg_id required", non_retryable=True)

    import shutil
    response_text: str
    provenance: str
    if shutil.which("codex"):
        model = models.default_for("adversary_1")
        result = await llm_io.call(
            model,
            system=_REVIEW_SYSTEM,
            user=_user_prompt(req, diff),
            msg_id=req.msg_id,
            repo=req.repo,
            pr=req.issue,
            max_tokens=400,
            temperature=0.0,
        )
        response_text = result.response
        provenance = f"{model.nick}{'-cached' if result.cached else ''}"
    else:
        # Subscription fallback — shell to claude. Same prompt, same
        # parsing. Less structural-reasoning specialty than codex, but
        # keeps the line running on subscription instead of API spend.
        response_text = await _claude_cli_review(_REVIEW_SYSTEM, _user_prompt(req, diff))
        provenance = "claude-cli-fallback"
    att = _capture(req.msg_id, "codex", response_text, worktree=req.worktree)
    att.verdict = _parse_verdict(response_text)
    att.provenance = provenance
    return att


async def _claude_cli_review(system: str, user: str) -> str:
    """Shell out to claude --print for one review pass. The combined
    prompt embeds the system instructions in the message because the
    CLI's --print mode is single-message. Returns the response text;
    raises ApplicationError on failure so the actor's andon catches it.
    Subprocess runs on a thread to keep the worker's asyncio loop free.
    """
    combined = f"{system}\n\n---\n\n{user}"
    try:
        result = await asyncio.to_thread(
            subprocess.run, ["claude", "--print", combined],
            capture_output=True, text=True, timeout=180,
        )
    except FileNotFoundError as e:
        raise ApplicationError(f"claude CLI fallback: not on PATH ({e})",
                               non_retryable=True)
    except subprocess.TimeoutExpired:
        raise ApplicationError("claude CLI fallback: exceeded 180s",
                               non_retryable=True)
    if result.returncode != 0:
        raise ApplicationError(
            f"claude CLI fallback: rc={result.returncode} {(result.stderr or '')[:300]}",
            non_retryable=True,
        )
    return result.stdout or ""


@activity.defn
async def gemini_review(req: QaOneEntryRequest, diff: str, round_num: int) -> GateAttestation:
    """Send diff to adversary_2 (gemini by default; haiku under test). Captures
    the raw response as the gate receipt."""
    if not req.msg_id:
        raise ApplicationError("msg_id required", non_retryable=True)

    model = models.default_for("adversary_2")
    result = await llm_io.call(
        model,
        system=_REVIEW_SYSTEM,
        user=_user_prompt(req, diff),
        msg_id=req.msg_id,
        repo=req.repo,
        pr=req.issue,
        max_tokens=400,
        temperature=0.0,
    )
    att = _capture(req.msg_id, f"gemini_r{round_num}", result.response,
                   worktree=req.worktree)
    att.verdict = _parse_verdict(result.response)
    att.provenance = f"{model.nick}-r{round_num}{'-cached' if result.cached else ''}"
    return att


async def qa_one_entry(req: QaOneEntryRequest) -> QaOneEntryResult:
    """Terminal-mode convenience composer. NOT an @activity.defn — the
    production path is QaActor composing test_attestation + codex_review +
    gemini_review as independent workflow.execute_activity calls.

    This wrapper exists so you can:
      - call the full qa pipeline from a script without standing up Temporal
      - debug end-to-end behavior in an interactive python shell
      - sanity-check the whole flow against Haiku-as-fixture

    Each sub-activity (test_attestation, codex_review, gemini_review) is its
    own @activity.defn and can be called independently for development in
    isolation. This composer just chains them inline.
    """
    if not req.msg_id:
        raise ApplicationError("msg_id required", non_retryable=True)
    if retro_state.is_halted():
        # Backpressure from the retro pager. Don't start a new qa cycle
        # while the human still owes Attend on pending SOAP one-pagers.
        observe.incr("halted_skip:qa")
        raise ApplicationError(
            "pipeline halted — clear a retro pager before running qa",
            non_retryable=False,  # retryable: clearing a pager resumes work
        )
    if control_state.is_paused():
        # Operator-initiated soft-pause. Retryable: clearing the flag
        # flips the gate and the next attempt walks through.
        observe.incr("paused_skip:qa")
        raise ApplicationError(
            "pipeline paused — clear `sweep pause off` before running qa",
            non_retryable=False,
        )

    start = time.time()
    test_att = await test_attestation(req)

    diff_proc = subprocess.run(
        ["git", "-C", req.worktree, "diff", "origin/HEAD..."],
        capture_output=True,
        text=True,
    )
    if diff_proc.returncode != 0:
        # `git diff origin/HEAD...` exits 128 when origin/HEAD is unset
        # (worktrees added via `git worktree add`, shallow clones without
        # --no-single-branch, repos provisioned without `gh repo clone`).
        # Falling through silently sends an empty diff to both reviewers,
        # who then return verdict: pass on nothing. Fail loud instead.
        raise ApplicationError(
            f"git diff failed (rc={diff_proc.returncode}): "
            f"{(diff_proc.stderr or '')[:300]}",
            non_retryable=True,
        )
    diff = diff_proc.stdout
    if not diff.strip():
        raise ApplicationError(
            "git diff returned empty — no changes between origin/HEAD and "
            "the fix branch; nothing for reviewers to attest",
            non_retryable=True,
        )

    codex_att = await codex_review(req, diff)
    gemini_first = await gemini_review(req, diff, 1)
    gemini_last = gemini_first

    sub_verdicts = {codex_att.verdict, gemini_last.verdict}
    if "fail" in sub_verdicts:
        verdict = "fail"
    elif sub_verdicts <= {"pass", "stubbed"}:
        verdict = "pass"
    else:  # "revise" present without "fail"
        verdict = "partial"

    result = QaOneEntryResult(
        msg_id=req.msg_id,
        verdict=verdict,
        bugs_found=0,
        test_attestation=test_att,
        codex=codex_att,
        gemini_first=gemini_first,
        gemini_last=gemini_last,
        elapsed_seconds=time.time() - start,
    )

    assert isinstance(result.bugs_found, int)
    assert Path(result.codex.artifact_path).exists()
    assert Path(result.gemini_last.artifact_path).exists()

    # Counter: one volley per qa_one_entry (codex + last gemini round).
    # Once cascade/loop is wired, the round count is gemini_last.rounds.
    rounds = max(getattr(result.gemini_last, "rounds", 1), 1)
    observe.incr("qa_volley", rounds)
    observe.incr(f"qa_volley_hist:{rounds}")
    observe.incr(f"qa_verdict:{verdict}")
    observe.incr(f"qa_volley:{req.repo}", rounds)
    observe.event(
        "qa_converged",
        msg_id=req.msg_id,
        repo=req.repo,
        pr=req.issue,
        branch=req.branch,
        verdict=verdict,
        rounds=rounds,
        sub_verdicts={"codex": codex_att.verdict, "gemini": gemini_last.verdict},
        elapsed_seconds=round(result.elapsed_seconds, 3),
    )
    return result
