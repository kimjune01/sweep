"""QA activities — single-entry, structurally bounded.

The activity signature *is* the WIP=1 enforcer. You cannot call qa_one_entry
with multiple repos or branches.
"""

from __future__ import annotations

import asyncio
import os
import re
import shlex
import subprocess
import time
from pathlib import Path

from temporalio import activity
from temporalio.exceptions import ApplicationError

from sweep import control_state, llm_io, models, observe, retro_params, retro_state
from sweep.io_safe import atomic_write_text
from sweep.types import GateAttestation, Message, QaOneEntryRequest, QaOneEntryResult


def is_repo_evicted(repo: str) -> bool:
    """Check whether `repo` is on the operator's evict list. Cards for
    evicted repos should short-circuit at activity entry — no point
    running an attest cycle when the operator has marked the repo
    out-of-rotation. Wraps `sift._on_evicted_list` so non-sift
    activities can share the check without importing sift's internals."""
    from sweep.activities.sift import _on_evicted_list, _on_kill_list
    return _on_evicted_list(repo) or _on_kill_list(repo)


@activity.defn(name="is_repo_evicted_activity")
async def is_repo_evicted_activity(repo: str) -> bool:
    """Temporal-callable wrapper so SkillActor / QaActor workflows can
    consult the eviction list from inside their loops (workflow code
    can't do filesystem reads directly). Pure delegation to
    is_repo_evicted."""
    return is_repo_evicted(repo)


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
        # Native is now an explicit operator opt-in (e.g. xcodebuild
        # repos that require macOS host). The previous "halt if
        # defaulted to native on darwin" gate is gone because the
        # default itself is `docker:sweep-tester:latest` — operators
        # only land here when they typed `sweep retro set ... test_env
        # native` deliberately. Trust the operator; no further check.
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
        # Image present locally? Check first via inspect (covers both
        # built-locally images like sweep-tester and pulled-from-registry
        # images that are already cached). Only fall through to `docker
        # pull` for registry images that aren't cached — pulling
        # `sweep-tester:latest` would fail with "repository does not
        # exist" because it's built locally, not on a registry.
        inspect = subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True, text=True, timeout=10,
        )
        if inspect.returncode != 0:
            # Not cached locally. For the fat image, that means the
            # operator hasn't built it yet — give the targeted message.
            if image == "sweep-tester:latest":
                raise ApplicationError(
                    f"test_env={env!r} but sweep-tester:latest isn't "
                    f"built locally. Run `sweep cache rebuild-image` "
                    f"(one-time, ~5-10 min). Then `sweep andon clear`.",
                    non_retryable=True,
                )
            # Registry image — try a pull.
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
        # Platform compatibility: the image's resolved arch must match
        # the host's, or runtime is qemu emulation — slow, flaky, and
        # produces misleading test failures attributable to the env
        # rather than the patch. Bail at the precondition rather than
        # let the test run and lie. (Front-load env checks; if the env
        # isn't possible here, attest can't honor its contract.)
        import platform as _platform
        inspect = subprocess.run(
            ["docker", "image", "inspect", "--format",
             "{{.Architecture}}", image],
            capture_output=True, text=True, timeout=10,
        )
        if inspect.returncode == 0:
            image_arch = inspect.stdout.strip()
            host_arch = {
                "x86_64": "amd64", "amd64": "amd64",
                "aarch64": "arm64", "arm64": "arm64",
            }.get(_platform.machine().lower(), _platform.machine().lower())
            if image_arch and image_arch != host_arch:
                raise ApplicationError(
                    f"test_env={env!r} resolved to image arch "
                    f"{image_arch!r} but host is {host_arch!r}. Running "
                    f"under qemu emulation produces unreliable test "
                    f"verdicts (misattributes env flakiness to the "
                    f"patch). Either pin a multi-arch / host-native "
                    f"image in retro_params, OR tighten sift's filter "
                    f"so {repo} isn't investigated on this host. Then "
                    f"`sweep andon clear`.",
                    non_retryable=True,
                )
        return env
    raise ApplicationError(
        f"unknown test_env {env!r}; expected 'native' or 'docker:<image>'",
        non_retryable=True,
    )


DEFAULT_TEST_ENV = "docker:sweep-tester:latest"


def _get_test_env(repo: str) -> tuple[str, str | None]:
    """Resolve (test_env, setup_cmd) for a repo from retro_params.

    Default is `docker:sweep-tester:latest` — the fat image built via
    `sweep cache rebuild-image` that carries Rust+Go+Python+Node+C++
    toolchains. Most OSS repos work in it.

    Overrides for the exceptions:
      sweep retro set <repo> test_env docker:rust:nightly  # specific image
      sweep retro set <repo> test_env native                # xcodebuild etc.

    setup_cmd: shell command run inside the container BEFORE test_cmd
               (e.g. "apt-get install -y libfoo-dev"). None when the
               fat image already covers the deps."""
    params = retro_params.resolved(repo)
    return (
        params.get("test_env", DEFAULT_TEST_ENV),
        params.get("test_setup_cmd"),
    )


BUILD_CACHE_ROOT = Path.home() / ".sweep" / "build-cache"
# Soft cap on total build-cache size. When exceeded, oldest repo dirs
# (by mtime — captures "when did cargo/go last write to target") are
# wiped until under cap. 20GB fits ~5-7 active Rust repos plus headroom
# for Go (modcache is smaller); raise via env if disk-rich.
BUILD_CACHE_MAX_GB = int(os.environ.get("SWEEP_BUILD_CACHE_MAX_GB", "20"))


def _du_bytes(path: Path) -> int:
    """Total bytes under path (follows no symlinks). Cheap shell out
    to du -sk; ~50ms warm even on multi-GB dirs."""
    try:
        r = subprocess.run(
            ["du", "-sk", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            return 0
        kb = int(r.stdout.split()[0])
        return kb * 1024
    except (subprocess.TimeoutExpired, ValueError, IndexError):
        return 0


def _prune_build_cache_if_full(max_gb: int = BUILD_CACHE_MAX_GB,
                                protect: Path | None = None) -> dict:
    """LRU-evict repo cache dirs with hysteresis: trigger at the cap,
    prune down to a lower recover floor. Without hysteresis the cache
    sits at 99-100% indefinitely (eviction fires the instant we
    breach, then a single new test refills it). The dead band keeps
    the cache below the warning threshold long enough for the
    operator-visible bar to actually read as "headroom present."

      trigger: total > max_gb        (e.g. > 20 GB)
      recover: prune until total < max_gb * RECOVER_FRAC (e.g. < 16 GB)

    Same TPS Trick #4 shape `should_idle` would use if it ever
    needed it: two thresholds, one signal, one direction.

    Ranking by mtime (write-time) rather than atime — atime is
    relatime-coarse on Linux and unreliable across mount types on
    macOS, but mtime accurately reflects "we wrote to target/" which
    is the read-write signal that matters for build caches.

    `protect` is the cache dir for the run that's about to fire — we
    never evict the dir we're about to use, even if it ranks oldest
    (e.g. a cold-restart on a previously-large cache could otherwise
    nuke its own working set). Concurrency safety against parallel
    attest runs is weaker but acceptable: SkillActor WIP=1 means
    attest is serial within itself; manual backfill races are rare
    and recoverable (next run cold-rebuilds the wiped dir)."""
    import shutil
    if not BUILD_CACHE_ROOT.exists():
        return {"action": "none", "reason": "no cache root"}
    total = _du_bytes(BUILD_CACHE_ROOT)
    cap = max_gb * 1024**3
    # Hysteresis: only trigger above the cap, then prune to the
    # lower recover floor. 0.8 = 20% dead band.
    RECOVER_FRAC = 0.8
    recover_floor = int(cap * RECOVER_FRAC)
    if total <= cap:
        return {"action": "none", "size_gb": round(total / 1024**3, 2),
                "cap_gb": max_gb,
                "recover_gb": round(recover_floor / 1024**3, 2)}
    # Above cap — prune to the recover floor, not the cap.
    cap = recover_floor
    dirs = sorted(
        [d for d in BUILD_CACHE_ROOT.iterdir() if d.is_dir()],
        key=lambda d: d.stat().st_mtime,
    )
    protect_resolved = protect.resolve() if protect else None
    deleted: list[dict] = []
    for d in dirs:
        if total < cap:
            break
        if protect_resolved and d.resolve() == protect_resolved:
            continue
        size = _du_bytes(d)
        try:
            shutil.rmtree(d)
        except OSError:
            continue
        total -= size
        deleted.append({"path": str(d), "size_gb": round(size / 1024**3, 2)})
    observe.event("build_cache_pruned",
                  cap_gb=max_gb,
                  final_size_gb=round(total / 1024**3, 2),
                  deleted_count=len(deleted),
                  deleted=deleted)
    return {"action": "prune", "deleted": deleted,
            "final_size_gb": round(total / 1024**3, 2),
            "cap_gb": max_gb}


async def _run_in_test_env(
    test_cmd: str, *, worktree: str, test_env: str, setup_cmd: str | None,
) -> subprocess.CompletedProcess:
    """Run test_cmd in the right environment. Native = host shell;
    docker:<image> = container with worktree mounted at /work and a
    persistent build cache mounted at /cache (CARGO_TARGET_DIR and
    GOCACHE/GOMODCACHE all point at it). Cache is per-repo under
    ~/.sweep/build-cache/<owner__repo> so successive runs amortize
    compile cost; total cache size is capped via
    _prune_build_cache_if_full (LRU by mtime).

    The setup_cmd runs once inside the container per invocation
    (cheap apt-get installs are mostly cached; first run is slow).
    No persistent setup-installed-state — we trade speed for
    determinism."""
    if test_env == "native":
        # Native is the operator-opt-in path for repos that need host
        # access (xcodebuild, kernel modules, GUI). For Xcode projects
        # we redirect DerivedData into the same per-repo cache dir the
        # docker branch uses, so xcodebuild's compiled outputs come
        # under sweep's LRU eviction (and become visible in `sweep
        # cache show`) instead of accumulating unbounded in
        # ~/Library/Developer/Xcode/DerivedData.
        wt = Path(worktree)
        env = os.environ.copy()
        is_xcode = any(wt.glob("*.xcodeproj")) or any(wt.glob("*.xcworkspace"))
        if is_xcode:
            cache_dir = BUILD_CACHE_ROOT / wt.name
            cache_dir.mkdir(parents=True, exist_ok=True)
            _prune_build_cache_if_full(protect=cache_dir)
            derived = cache_dir / "xcode-derived-data"
            derived.mkdir(exist_ok=True)
            # IDEDerivedDataPathOverride is the env-var equivalent of
            # the `-derivedDataPath` xcodebuild flag — works even when
            # the operator's test_cmd doesn't pass it explicitly.
            env["IDEDerivedDataPathOverride"] = str(derived)
        return await asyncio.to_thread(
            subprocess.run, shlex.split(test_cmd),
            cwd=worktree, capture_output=True, text=True, env=env,
        )
    if not test_env.startswith("docker:"):
        raise ApplicationError(
            f"unknown test_env {test_env!r}; expected 'native' or 'docker:<image>'",
            non_retryable=True,
        )
    image = test_env.removeprefix("docker:")
    cache_dir = BUILD_CACHE_ROOT / Path(worktree).name
    cache_dir.mkdir(parents=True, exist_ok=True)
    # LRU-prune before using the cache so we don't blow past the cap
    # mid-run. Protect this run's cache_dir from eviction.
    _prune_build_cache_if_full(protect=cache_dir)
    inner = f"{setup_cmd} && {test_cmd}" if setup_cmd else test_cmd
    docker_args = [
        "docker", "run", "--rm",
        "-v", f"{worktree}:/work", "-w", "/work",
        "-v", f"{cache_dir}:/cache",
        # Cargo writes the compile output dir here.
        "-e", "CARGO_TARGET_DIR=/cache",
        # Go's two caches: module download cache and build artifact
        # cache. Harmless when the image isn't golang — Go honors them
        # only when the toolchain is invoked.
        "-e", "GOMODCACHE=/cache/gomod",
        "-e", "GOCACHE=/cache/gobuild",
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
                       attestation_hash: str | None = None,
                       worktree: str | None = None,
                       incoming: Message | None = None) -> str | None:
    """Deposit a card on qa.jsonl and signal qa-actor. Called by
    investigate_cycle on the production lane when a fresh fix branch
    is ready for verification. Reqa-actor handles the engagement-lane
    equivalent via kick_reqa_card."""
    import datetime as _dt
    import json as _json
    from dataclasses import asdict as _asdict
    from sweep.types import Message, forward_ledger
    from sweep.activities.pr_state import _signal_actor

    ts = _dt.datetime.now(_dt.timezone.utc)
    slug = repo.replace("/", "-")
    pr_part = pr if pr is not None else "new"
    msg_id = f"qa-{ts.strftime('%Y%m%dT%H%M%S')}-{slug}-{pr_part}"
    payload: dict = {}
    if attestation_hash:
        payload["attestation_hash"] = attestation_hash
    if worktree:
        payload["worktree"] = worktree
    msg = Message(
        msg_id=msg_id,
        sender=sender,
        intent="reattest",
        repo=repo,
        pr=pr,
        branch=branch,
        payload=payload,
        ts=ts.isoformat(),
        ledger=forward_ledger(incoming),
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


def _looks_like_env_artifact(master_slice: str, fix_slice: str) -> bool:
    """True iff the master and fix failures look like the SAME env-class
    error — meaning the substrate's container is the problem, not the
    PR's code. Heuristic: if both slices contain the same compile-time
    failure signature (undefined reference, missing header, build-
    script failure, linker error), the test isn't running because the
    build broke the same way on both branches. The PR can't be the
    cause of a pre-test build failure.

    Conservative: requires BOTH a compile-class anchor in the fix slice
    AND a substantively-overlapping anchor in master. Misses are OK —
    we just fall through to the existing test_fails_on_fix path."""
    import re as _re
    if not master_slice or not fix_slice:
        return False
    # Compile-class anchors. Order matters only insofar as we score
    # whichever appears in both.
    anchors = [
        "undefined reference to",
        "cannot find -l",
        "fatal error:",
        "error: linking with",
        "failed to run custom build command for",
        "ld: error",
        "ld returned",
        "collect2: error",
        "configure: error",
        "make: *** No rule to make target",
    ]
    def _norm(s: str) -> str:
        # Strip register hex, line numbers, path prefixes — the
        # instance-level noise. Keep the structural error vocabulary.
        s = _re.sub(r"0x[0-9a-f]+", "<HEX>", s)
        s = _re.sub(r":\d+(:\d+)?", ":<LN>", s)
        s = _re.sub(r"/[\w./-]+/", "<PATH>/", s)
        return s
    m_norm = _norm(master_slice)
    f_norm = _norm(fix_slice)
    shared = [a for a in anchors if a in m_norm and a in f_norm]
    if not shared:
        return False
    # At least one compile-class anchor in both → env_artifact.
    return True


def _slice_around_error(stderr: str, *, budget: int = 800) -> str:
    """Surface the actual failure reason from a cargo/build stderr.

    Plain head- or tail-clipping misses the real error: cargo dumps the
    full linker command (5-10KB of `-Wl,...` flags) between the noise
    and the error line. Scans for the LAST line beginning with `error:`,
    `error[`, `fatal:`, or `panicked at` and returns a window around it.
    Falls back to the tail if no such line is found.

    Linker-failure augmentation: when the anchor's window contains
    `extern functions couldn't be found` (cargo's generic linker-fail
    message), additionally surface up to 4 sample `undefined reference`
    lines AND any `cannot find -l<lib>` lines from earlier in stderr.
    Without this, the autofix detector + operator both see a generic
    "some native libraries may need to be installed" with no clue
    which library — exactly the polars-utils → libpython case where
    the symbol names (PyErr_*, PyTuple_Type, ...) are the diagnostic
    but get truncated out of the window.
    """
    if not stderr:
        return ""
    lines = stderr.splitlines()
    anchor_idx = -1
    for i, ln in enumerate(lines):
        s = ln.lstrip()
        if (s.startswith("error:") or s.startswith("error[")
                or s.startswith("fatal:") or s.startswith("panicked at")
                or s.startswith("FAILED") or s.startswith("FAIL")):
            anchor_idx = i
    if anchor_idx < 0:
        return f"...{stderr[-budget:]}"
    window = "\n".join(lines[max(0, anchor_idx - 5):anchor_idx + 8])

    # Linker-fail augmentation.
    if ("extern functions couldn't be found" in window
            or "cannot find -l" in window):
        undef_refs: list[str] = []
        cannot_find: list[str] = []
        for ln in lines[:anchor_idx]:
            s = ln.strip()
            if "undefined reference to" in s and len(undef_refs) < 4:
                undef_refs.append(s)
            elif "cannot find -l" in s and s not in cannot_find:
                cannot_find.append(s)
        diag = ""
        if undef_refs:
            diag += "\n--- sample undefined references ---\n" + "\n".join(undef_refs)
        if cannot_find:
            diag += "\n--- cannot find linker libs ---\n" + "\n".join(cannot_find)
        window = window + diag

    if len(window) > budget:
        window = window[:budget // 2] + "..." + window[-budget // 2:]
    return window


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


def _looks_like_test(path: str) -> bool:
    """Heuristic: is this file a test file? Used by test_attestation to
    extract the test-only slice of a fix-branch diff and apply it to
    master, so PRs that add new tests get gated on "does the new test
    fail on master" rather than "does the unchanged master test suite
    pass." False positives here just mean we apply too much (worst
    case: master fails for an unrelated reason and we still route to
    reinvestigate, which is recoverable). False negatives are worse —
    a missed test file means the gate keeps tripping at
    test_passes_on_master."""
    p = path.lower()
    # Path-segment markers — directories that conventionally hold tests
    # in every language ecosystem we attest against.
    seg_markers = ("/test/", "/tests/", "/__tests__/", "/spec/", "/specs/")
    if any(m in f"/{p}/" for m in seg_markers):
        return True
    # Filename suffixes / prefixes — language-specific test naming.
    base = p.rsplit("/", 1)[-1]
    if (
        base.endswith("_test.go")           # Go
        or base.endswith("_test.py")         # Python
        or base.startswith("test_")          # Python (pytest discovery)
        or ".test." in base                  # JS/TS Jest etc.
        or ".spec." in base                  # JS/TS Mocha/Jasmine etc.
        or base.endswith("_spec.rb")         # Ruby RSpec
        or base.endswith("_test.exs")        # Elixir
    ):
        return True
    # Rust convention: `#[cfg(test)]` lives in regular .rs files, but
    # `tests/*.rs` (integration tests) and `benches/*.rs` are the
    # path-shaped slice — covered by the seg_markers above.
    return False


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

    # PR may ADD a new test alongside the fix. If we run the existing
    # test suite as-is on master, the new test isn't there and master
    # trivially passes — gate trips on `test_passes_on_master` despite
    # the fix being real. Extract just the test-file changes from the
    # fix branch and apply them onto master, so the new test runs
    # against the unfixed code (where it must fail). havener#1033 was
    # the witness: the PR's new test exercised math.Round behavior,
    # but master's test_cmd alone never executed it.
    test_diff_files = await _run([
        "git", "diff", "--name-only", default, req.branch, "--",
    ])
    candidate_files = [f for f in (test_diff_files.stdout or "").splitlines() if f]
    test_files = [f for f in candidate_files if _looks_like_test(f)]
    log.append(f"changed_test_files={len(test_files)}/{len(candidate_files)}")

    # No tests in PR is a distinct shape from "test passes on master."
    # Raise its own verdict so the operator sees the real diagnosis
    # ("PR ships without tests; can't attest") instead of the
    # misleading "bug fixed upstream or test wrong" framing. The fix
    # is to add a test, not to investigate whether the fix is real.
    # evebox#369 was the witness — CLI flag added, no test exercising
    # it; previously halted on test_passes_on_master with no clue why.
    if candidate_files and not test_files:
        raise ApplicationError(
            f"no_tests_in_pr — PR changed {len(candidate_files)} files "
            f"but none look like tests "
            f"(first: {candidate_files[0]!r}). Without a test the "
            f"fail-on-master/pass-on-fix gate can't run. Operator path: "
            f"either write a test that fails on master + passes on the "
            f"fix and re-attest, or close the PR as unverifiable.",
            non_retryable=True,
        )

    if test_files:
        diff_proc = await _run(
            ["git", "diff", default, req.branch, "--"] + test_files
        )
        diff_text = diff_proc.stdout or ""
        if diff_text.strip():
            apply_proc = await asyncio.to_thread(
                subprocess.run,
                ["git", "apply", "--whitespace=nowarn", "--allow-empty", "-"],
                cwd=worktree, input=diff_text, capture_output=True, text=True,
            )
            if apply_proc.returncode != 0:
                # Patch couldn't apply — fall through to running master
                # as-is. Surface why so the operator can read the log;
                # don't halt, since the post-apply check below catches
                # the real semantic problem (master must fail).
                log.append(
                    f"test_diff_apply_failed: {(apply_proc.stderr or '')[:200]}"
                )
            else:
                log.append(f"applied_test_diff_bytes={len(diff_text)}")

    _heartbeat({"stage": "test_on_master"})
    master_run = await _run_in_test_env(
        req.test_cmd, worktree=worktree, test_env=test_env, setup_cmd=setup_cmd,
    )
    log.append(f"master ({default}) exit={master_run.returncode} env={test_env}")
    if master_run.returncode == 0:
        raise ApplicationError(
            "test_passes_on_master — bug fixed upstream or test wrong "
            f"(applied {len(test_files)} test files from fix branch)",
            non_retryable=True,
        )

    # Restore master to clean state before checking out the fix branch,
    # so the applied test-diff doesn't conflict with the checkout.
    await _run(["git", "checkout", "--quiet", "HEAD", "--", "."])
    await _run(["git", "clean", "-fdq"])

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
        # Env-artifact detection: master had to fail (the upstream gate)
        # AND fix also failed. If both failures look like the SAME
        # error — build/link error, missing system header, docker-root
        # chmod skew, Catch2 env mismatch — the substrate's local env
        # is the problem, not the PR's code. Route to env_artifact so
        # attest sinks the PR with OPEN_ENV_ARTIFACT (we did what we
        # could; upstream CI is ground truth). Distinct from
        # test_fails_on_fix where master fails the way we expect AND
        # fix fails differently (real bug).
        master_slice = _slice_around_error(master_run.stderr)
        fix_slice = _slice_around_error(fix_run.stderr)
        if _looks_like_env_artifact(master_slice, fix_slice):
            raise ApplicationError(
                f"env_artifact — substrate env failed on both branches: "
                f"{fix_slice[:600]}",
                non_retryable=True,
            )
        # Slice around the last `error:` or `error[Exxx]:` line. Plain
        # tail-clipping lands inside rustc's link-command dump (kilobytes
        # of `-Wl,...` flags) before the actual error. Finding the last
        # error line + grabbing a window around it surfaces the cause
        # regardless of how big the preamble is.
        raise ApplicationError(
            f"test_fails_on_fix — fix is broken: {fix_slice}",
            non_retryable=True,
        )

    body = "\n".join(log) + "\n\n--- master stderr ---\n" + master_run.stderr + "\n--- fix stdout ---\n" + fix_run.stdout
    att = _capture(req.msg_id, "test", body, worktree=req.worktree)
    att.verdict = "pass"

    # Write the attestation triple into OUR sweep repo's working tree,
    # not the fork's worktree. Layout:
    #   <sweep>/attestations/<org>-<repo>/issue-<n>-{manifest,before,after}
    # Per-repo dir, flat issue-prefixed files — easy to browse.
    # Local-only step: qa owns the test runs and the file write (it has
    # the stdout). The commit + push to our sweep repo, the rendered
    # public link, and the amend fan-out all live in attest_cycle —
    # "qa pushes to their repo, attest pushes to our repo."
    try:
        from sweep.attestation_writer import write_attestation_files
        import platform
        sweep_repo = Path(__file__).resolve().parent.parent.parent
        org_repo = req.repo.replace("/", "-")
        attestation_dir = sweep_repo / "attestations" / org_repo
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
    except Exception as e:
        observe.event("attestation_write_failed", msg_id=req.msg_id,
                      error_type=type(e).__name__, error=str(e)[:200])

    return att


_REVIEW_SYSTEM = (
    "You are a structural code reviewer. Read the diff and decide whether "
    "the change is sound. Output JSON only (no prose, no markdown fences), "
    "matching this schema:\n\n"
    "{\n"
    '  "verdict": "pass" | "fail" | "revise",\n'
    '  "key_issues": [str],   // concrete concerns; empty list if clean\n'
    '  "rationale": str       // one or two sentences, <120 words total\n'
    "}\n\n"
    "Most of the time you should be able to comply. When you can't (diff "
    "unreadable, off-topic, can't evaluate), output an empty string — empty "
    "is a legal answer and is preferable to fabricating a verdict you don't "
    "believe. A downstream sonnet shim parses your output; native JSON saves "
    "it work and is more reliable than prose extraction."
)


def _user_prompt(req: QaOneEntryRequest, diff: str) -> str:
    head = f"Repo: {req.repo}\nBranch: {req.branch}"
    if req.issue is not None:
        head += f"\nIssue: #{req.issue}"
    return f"{head}\n\nDiff to review:\n\n{diff}"


def _parse_verdict(response: str) -> str:
    """Best-effort verdict extraction from a single reviewer's raw text.
    The authoritative fuse uses `extract_qa_verdicts` (sonnet shim) at
    the qa_one_entry / qa_actor level; this regex stays only so each
    individual GateAttestation has *some* verdict for observability when
    the activity returns to its caller.

    Reviewers are now prompted to output JSON ({"verdict": "...", ...});
    try JSON first, fall back to the legacy `verdict: X` regex if the
    reviewer didn't comply. Stubs return 'stubbed'; anything else
    unparsed returns 'revise' so the cascade keeps moving rather than
    auto-passing on garbled output."""
    import json as _json
    if response.startswith("<stub:"):
        return "stubbed"
    text = response.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].lstrip()
    try:
        d = _json.loads(text)
        v = str(d.get("verdict", "")).lower()
        if v in ("pass", "fail", "revise"):
            return v
    except (_json.JSONDecodeError, AttributeError):
        pass
    m = re.search(r"verdict\s*:\s*(pass|fail|revise)", response, re.IGNORECASE)
    if not m:
        return "revise"
    return m.group(1).lower()


_SHIM_SYSTEM = (
    "You are a structured-output parser for code review verdicts. You "
    "receive two reviewers' raw prose and return JSON. Read each "
    "reviewer's reasoning and extract the actual verdict (which may "
    "contradict their literal 'verdict:' line if their reasoning says "
    "otherwise). Then fuse the two into a single decisive verdict.\n\n"
    "Output schema (JSON only, no prose, no markdown fences):\n"
    "{\n"
    '  "codex":  {"verdict": "pass|fail|revise", "key_issues": [str], "rationale": str},\n'
    '  "claude": {"verdict": "pass|fail|revise", "key_issues": [str], "rationale": str},\n'
    '  "fused":  {"verdict": "pass|fail|partial", "reason": str}\n'
    "}\n\n"
    "Fuse rules: any 'fail' → fused 'fail'. All 'pass' → fused 'pass'. "
    "Any 'revise' without 'fail' → fused 'partial'. Reasons should be "
    "one short sentence each. key_issues are concrete concerns named "
    "in the prose; empty list if the reviewer was clean."
)


@activity.defn
async def read_artifact_texts(codex_path: str,
                               claude_path: str) -> dict:
    """Read both reviewer attestation files. Lives as an activity so
    the workflow body never touches the filesystem directly (Temporal's
    deterministic sandbox blocks `Path.read_text` from inside workflows).
    """
    from pathlib import Path as _Path
    return {
        "codex": _Path(codex_path).read_text(),
        "claude": _Path(claude_path).read_text(),
    }


@activity.defn
async def extract_qa_verdicts(codex_response: str,
                               claude_response: str,
                               msg_id: str | None = None,
                               repo: str | None = None,
                               pr: int | None = None) -> dict:
    """Sonnet shim that turns two reviewers' raw prose into structured
    verdicts + a fused decision. Replaces the regex parser in the fuse
    path; each reviewer's GateAttestation still carries its own
    regex-extracted verdict for activity-level observability.

    JSON-only output enforced via the system prompt. If sonnet returns
    malformed JSON, the activity raises ApplicationError(non_retryable)
    so the actor's andon cord fires — we trust sonnet enough that
    malformed output is an outage signal, not noise to swallow."""
    import json as _json
    from sweep import llm_io as _llm_io, models as _models

    user = (
        f"Reviewer A (codex):\n{codex_response}\n\n"
        f"---\n\n"
        f"Reviewer B (claude):\n{claude_response}\n\n"
        f"---\n\n"
        f"Return the JSON object now."
    )
    result = await _llm_io.call(
        _models.resolve("sonnet"),
        system=_SHIM_SYSTEM,
        user=user,
        msg_id=msg_id, repo=repo, pr=pr,
        max_tokens=800, temperature=0.0,
    )
    text = (result.response or "").strip()
    # Strip accidental markdown fences if the model adds them despite
    # the system prompt. Cheap safety net; not a real parsing fallback.
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].lstrip()
    try:
        data = _json.loads(text)
    except _json.JSONDecodeError as e:
        raise ApplicationError(
            f"verdict shim returned malformed JSON: {e}; "
            f"first 200 chars: {text[:200]!r}",
            non_retryable=True,
        ) from e
    # Lightweight shape check — missing top-level keys are also a shim
    # outage, not a default-to-pass situation.
    for key in ("codex", "claude", "fused"):
        if key not in data:
            raise ApplicationError(
                f"verdict shim missing top-level key {key!r}; got keys: "
                f"{list(data.keys())}",
                non_retryable=True,
            )
    return data


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
    """Adversary_2 review via the model `adversary_2` role resolves to
    (sonnet by default). Pairs with codex_review (adversary_1, codex
    CLI) for the volley: codex brings OpenAI-side structural reasoning,
    sonnet brings Anthropic-side review that diverges from opus (the
    writer of the fix). Claude CLI is the SHIM role (extract_qa_verdicts),
    not an adversary slot.

    Function name kept (rename would ripple through worker/qa_actor/cli)
    but the route uses llm_io and pays Anthropic API spend on each call
    — small at 5-10 qa cycles/day. See models.py for cascade rationale."""
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

    # synth_test — write a regression test if the fix lacks one. Runs
    # before test_attestation so the gate sees the synthesized test in
    # the diff and can verify it via fail-on-master/pass-on-fix. On
    # punt (no issue ref, vague issue, etc.) the gate falls through to
    # the existing no_tests_in_pr verdict. Same wiring as qa_actor's
    # production path so qa_one_entry callers (reqa, terminal mode)
    # also get the test-writing intercept.
    if req.issue:
        try:
            from sweep.activities.synth_test import synth_test_for_fix
            await synth_test_for_fix(
                req.repo, req.branch, req.worktree, req.issue,
                issue_number=req.issue, pr_body=None,
            )
        except Exception:
            pass  # punt path; attest will emit no_tests_in_pr if still missing

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

    # Sonnet shim — authoritative verdict + structured per-reviewer
    # extraction. Replaces the old regex+set-fuse path which couldn't
    # tell "verdict: pass but reasoning lists three blockers" from a
    # clean pass. Raw responses live in the artifact files captured by
    # each review activity; read them back to feed the shim.
    codex_text = Path(codex_att.artifact_path).read_text()
    claude_text = Path(gemini_last.artifact_path).read_text()
    shim = await extract_qa_verdicts(
        codex_text, claude_text,
        msg_id=req.msg_id, repo=req.repo, pr=req.issue,
    )
    verdict = shim["fused"]["verdict"]
    codex_att.verdict = shim["codex"]["verdict"]
    gemini_last.verdict = shim["claude"]["verdict"]

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
