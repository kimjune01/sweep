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
    `=== path ===` separators. Keeps the prompt budget tight."""
    chunks: list[str] = []
    budget = 6000
    for rel in _SIGNAL_FILES:
        path = worktree / rel
        if not path.exists() or not path.is_file():
            continue
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        if not text.strip():
            continue
        slice_ = text[:1500]
        chunk = f"=== {rel} ===\n{slice_}\n"
        if len(chunk) > budget:
            break
        chunks.append(chunk)
        budget -= len(chunk)
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
    system = (
        "You read a repository's manifest and CI files and answer with "
        "the single shell command a maintainer would run locally to "
        "execute the test suite. One line, no backticks, no prose, no "
        "explanation, no leading $. If the repo doesn't have tests, "
        "the convention is unclear, or the inputs are unreadable, "
        "output nothing. Empty is a legal answer; do not guess at a "
        "command you don't have evidence for."
    )
    user = (
        f"Repository: {repo}\n\n"
        f"Selected files (truncated):\n\n{signals or '(no recognizable manifest files)'}\n\n"
        "Canonical local test command:"
    )
    try:
        out = await asyncio.to_thread(llm_cli.call, system, user, timeout_s=120)
    except Exception as e:
        raise ApplicationError(f"infer_test_cmd LLM call failed: {e}",
                               non_retryable=True)
    cmd = out.strip().splitlines()[0].strip() if out else ""
    # Strip common LLM artifacts.
    for prefix in ("$ ", "> ", "`"):
        if cmd.startswith(prefix):
            cmd = cmd[len(prefix):].strip()
    if cmd.endswith("`"):
        cmd = cmd[:-1].strip()
    if not cmd or cmd.upper() == "NONE":
        raise ApplicationError(
            f"infer_test_cmd: no test convention detected for {repo}",
            non_retryable=True,
        )
    # Cache so subsequent qa cycles skip the LLM round-trip.
    retro_params.append(repo, key="test_cmd", value=cmd, reason="inferred by infer_test_cmd")
    return cmd
