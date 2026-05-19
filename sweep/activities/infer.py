"""LLM-shaped inference activities — fuzzy reads over a worktree.

Currently: `infer_test_cmd(worktree, repo)` figures out the canonical
test command by reading the repo's manifest files and CI config. Caches
the result in `retro_params` per repo so we only ask once per repo per
policy change.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from temporalio import activity
from temporalio.exceptions import ApplicationError

from sweep import llm_cli, retro_params

# Files that strongly signal the test convention. We read them (truncated)
# into the LLM prompt. Order doesn't matter; the LLM looks at all of them.
_SIGNAL_FILES = (
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "Cargo.toml",
    "package.json",
    "go.mod",
    "Makefile",
    "justfile",
    "tox.ini",
    "pytest.ini",
    ".github/workflows/test.yml",
    ".github/workflows/ci.yml",
    "CONTRIBUTING.md",
    "README.md",
)


def _collect_signals(worktree: Path) -> str:
    """Read up to ~6KB total across the signal files; concatenate with
    `=== path ===` separators. Keeps the prompt budget tight.

    Also scans immediate subdirs (depth=1) for the same signal files.
    Repos that put their build manifest under `src/` (Go-style — see
    KaijuEngine/kaiju), `crates/<name>/` (Rust workspaces), or
    `packages/<name>/` (JS monorepos) need the subdir hint so the LLM
    can prefix the test command with `cd <subdir>`. Without this, the
    root-only scan returned empty signals and the LLM guessed a
    plain `go test ./...` that fails with "directory prefix . does
    not contain main module."
    """
    chunks: list[str] = []
    budget = 6000

    def _try_add(rel_path: Path, display: str) -> bool:
        """Add the file at rel_path to chunks under `=== display ===`
        if it exists, is non-empty, and fits in the remaining budget.
        Returns True if added (caller updates budget)."""
        nonlocal budget
        if not rel_path.exists() or not rel_path.is_file():
            return False
        try:
            text = rel_path.read_text(errors="replace")
        except OSError:
            return False
        if not text.strip():
            return False
        slice_ = text[:1500]
        chunk = f"=== {display} ===\n{slice_}\n"
        if len(chunk) > budget:
            return False
        chunks.append(chunk)
        budget -= len(chunk)
        return True

    # Root pass.
    for rel in _SIGNAL_FILES:
        _try_add(worktree / rel, rel)

    # Subdir pass (depth=1). Skip hidden/build/vendor dirs that almost
    # never carry the canonical manifest.
    _SKIP_SUBDIRS = {"node_modules", "vendor", "target", "dist", "build",
                     ".git", ".github", ".idea", ".vscode", "docs"}
    if budget > 500:
        try:
            subdirs = sorted(
                p for p in worktree.iterdir()
                if p.is_dir()
                and not p.name.startswith(".")
                and p.name not in _SKIP_SUBDIRS
            )
        except OSError:
            subdirs = []
        for sub in subdirs:
            if budget <= 500:
                break
            for rel in _SIGNAL_FILES:
                if budget <= 500:
                    break
                _try_add(sub / rel, f"{sub.name}/{rel}")

    return "".join(chunks)


@activity.defn
async def infer_test_cmd(worktree: str, repo: str) -> str:
    """Return the canonical test command for `repo` (single line, no
    explanation). Reads retro_params first so we don't re-ask. On miss,
    calls the orchestrate LLM with the manifest/CI files as context,
    caches the result back into retro_params.
    """
    if not worktree:
        raise ApplicationError("infer_test_cmd: worktree required",
                               non_retryable=True)
    cached = retro_params.resolved(repo).get("test_cmd")
    if cached:
        return cached

    tree = Path(worktree)
    if not (tree / ".git").exists():
        raise ApplicationError(
            f"infer_test_cmd: {worktree} is not a git worktree",
            non_retryable=True,
        )
    signals = _collect_signals(tree)
    # Lockfile presence — tells the model to prefix install step when
    # the test runner needs deps installed first. Test runs in a clean
    # container with the worktree mounted read-only-ish; deps from the
    # manifest aren't pre-installed.
    lockfiles: list[str] = []
    for lock_rel in ("package-lock.json", "pnpm-lock.yaml", "yarn.lock",
                      "Cargo.lock", "go.sum", "poetry.lock", "uv.lock"):
        # Check root + immediate subdirs (same depth as _collect_signals).
        if (tree / lock_rel).exists():
            lockfiles.append(lock_rel)
            continue
        try:
            for sub in tree.iterdir():
                if sub.is_dir() and not sub.name.startswith(".") and (sub / lock_rel).exists():
                    lockfiles.append(f"{sub.name}/{lock_rel}")
                    break
        except OSError:
            pass
    lockfile_hint = (
        f"Lockfiles present: {', '.join(lockfiles)}\n\n"
        if lockfiles else ""
    )
    system = (
        "You read a repository's manifest and CI files and answer with "
        "the single shell command a maintainer would run locally to "
        "execute the test suite. One line, no backticks, no prose, no "
        "explanation, no leading $. If the repo doesn't have tests, "
        "the convention is unclear, or the inputs are unreadable, "
        "output nothing. Empty is a legal answer; do not guess at a "
        "command you don't have evidence for.\n\n"
        "Tests run in a CLEAN container — no deps pre-installed. If a "
        "lockfile is present and the test runner needs deps (vitest, "
        "jest, mocha, pytest with editable installs, etc.), PREFIX with "
        "the install step:\n"
        "  package-lock.json → `npm ci && ...`\n"
        "  pnpm-lock.yaml    → `pnpm install --frozen-lockfile && ...`\n"
        "  yarn.lock         → `yarn install --frozen-lockfile && ...`\n"
        "  poetry.lock       → `poetry install --no-interaction && ...`\n"
        "  uv.lock           → `uv sync && uv run ...`\n"
        "Cargo and go test resolve deps as part of the test run itself, "
        "so no install prefix needed for those. If the manifest is in a "
        "subdir (e.g. `src/go.mod`, `crates/foo/Cargo.toml`), wrap with "
        "`cd <subdir> && ...`."
    )
    user = (
        f"Repository: {repo}\n\n"
        f"{lockfile_hint}"
        f"Selected files (truncated):\n\n{signals or '(no recognizable manifest files)'}\n\n"
        "Canonical local test command:"
    )
    # Retry-once on transient claude CLI flakiness (empty stdout,
    # subprocess timeout, broken pipe). The first failure is almost
    # always recoverable; halting the actor on it makes octave#94 a
    # recurring rock when claude has a bad second. Second failure is
    # a real signal — propagate as halt.
    async def _try_once():
        # allow_empty=True: the system prompt explicitly says empty is
        # legal ("no tests / convention unclear / unreadable inputs").
        # Without this flag llm_cli treats empty as structural failure
        # and the actor andons on a perfectly correct LLM answer.
        return await asyncio.to_thread(
            lambda: llm_cli.call(system, user, timeout_s=120,
                                  allow_empty=True),
        )

    last_err: Exception | None = None
    out = ""
    for attempt in (1, 2):
        try:
            out = await _try_once()
        except Exception as e:
            last_err = e
            if attempt == 1:
                # Brief backoff between attempts so we're not racing
                # the same flake.
                await asyncio.sleep(2)
                continue
            raise ApplicationError(
                f"infer_test_cmd LLM call failed (after retry): {e}",
                non_retryable=True,
            )
        # Empty stdout is legal per the system prompt ("no tests /
        # convention unclear / unreadable"). Retry once for transient
        # flakiness, then accept empty as the model's "I don't know"
        # answer. We mark the repo and return "" — caller decides
        # what to do; halting the actor on a perfectly correct LLM
        # answer was the wrong shape.
        if not (out or "").strip() and attempt == 1:
            await asyncio.sleep(2)
            continue
        break
    cmd = out.strip().splitlines()[0].strip() if out else ""
    # Strip common LLM artifacts.
    for prefix in ("$ ", "> ", "`"):
        if cmd.startswith(prefix):
            cmd = cmd[len(prefix):].strip()
    if cmd.endswith("`"):
        cmd = cmd[:-1].strip()
    if not cmd or cmd.upper() == "NONE":
        # Mark the repo as "no test cmd known" so future qa cycles
        # skip rather than re-burning the LLM call. Caller (attest /
        # qa) sees the empty return value and short-circuits the
        # test_attestation step.
        retro_params.append(repo, key="test_cmd", value="",
                            reason="inferred empty: no test convention")
        return ""
    # Cache so subsequent qa cycles skip the LLM round-trip.
    retro_params.append(repo, key="test_cmd", value=cmd, reason="inferred by infer_test_cmd")
    return cmd
