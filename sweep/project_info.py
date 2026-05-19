"""project_info — single source of truth for "where does this project
live and how is it built?"

Every actor and CLI that needs to operate on a repo (investigate, qa,
reqa, synth_test, evict, retro) should call `info(repo)` rather than
reconstructing the worktree path or peeking at retro_params on its own.
Centralizing the lookup is what stops investigate from writing fixes
shaped for the host while qa judges them in docker (or vice versa).

The module is read-only data assembly: it gathers facts already living
in worktree.py, retro_params, and the eviction list, and returns them
as one dataclass. Operator overrides flow through retro_params as
before; this is the read-side accessor.

CLI counterpart: `sweep project-info <repo>` emits the same data as
JSON, so LLM-spawned subprocesses inside /investigate or /synth-test
can shell out with `sweep project-info $REPO` and parse the result.
That gives the writer the same env knowledge the verifier already has,
killing the routing-drift class of bugs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from sweep import retro_params
from sweep.activities.qa import DEFAULT_TEST_ENV, is_repo_evicted
from sweep.activities.worktree import WORKTREE_ROOT


@dataclass
class ProjectInfo:
    """Canonical view of a repo's local state. All paths absolute."""
    repo: str
    worktree: str
    worktree_exists: bool
    test_env: str
    test_cmd: str | None
    test_setup_cmd: str | None
    evicted: bool
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def info(repo: str) -> ProjectInfo:
    """Resolve a repo's project info. Always returns a ProjectInfo;
    fields are None / defaults when a value hasn't been set yet (a
    repo that roll hasn't touched will have test_cmd=None and
    worktree_exists=False, which is the honest signal)."""
    params = retro_params.resolved(repo)
    worktree = WORKTREE_ROOT / repo.replace("/", "__")
    notes: list[str] = []

    test_env = params.get("test_env", DEFAULT_TEST_ENV)
    if "test_env" in params:
        notes.append(f"test_env overridden via retro_params: {test_env}")
    else:
        notes.append("test_env defaulted to sweep-tester image")

    test_cmd = params.get("test_cmd")
    test_setup_cmd = params.get("test_setup_cmd")

    evicted = is_repo_evicted(repo)
    if evicted:
        notes.append("repo is on the eviction list; activity-entry "
                     "short-circuit will drop cards before any work")

    return ProjectInfo(
        repo=repo,
        worktree=str(worktree),
        worktree_exists=worktree.exists(),
        test_env=test_env,
        test_cmd=test_cmd,
        test_setup_cmd=test_setup_cmd,
        evicted=evicted,
        notes=notes,
    )
