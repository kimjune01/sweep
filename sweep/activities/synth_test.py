"""synth_test — write a regression test for a fix that lacks one.

Called by qa_actor when the fix-branch diff against master adds no test
files (the `_looks_like_test` heuristic returns false for every changed
path). The synth agent is shown:

  - the issue text (gh issue view)
  - the master-side (unfixed) content of the files the fix modified
  - one or two sibling test files from the repo as convention examples

It is NOT shown the fix diff or the fix-branch content. That hiding is
deliberate: a writer that sees the fix will mirror it (tautological tests
that verify the implementation, not the behavior). The writer derives
the test from the issue's described behavior against the unfixed code,
like a TDD-style human author would.

The attest gate is the independent verifier — see memory/feedback_writer
_naive_of_verifier.md for the architectural principle.

Punt conditions (return without committing, qa falls through to existing
no_tests_in_pr verdict):
  - No issue ref in PR body
  - Issue text empty / vague
  - Skill writes `SYNTH_PUNTED: <reason>` to stdout
  - No claude CLI on PATH (raises non-retryable)
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from temporalio import activity
from temporalio.exceptions import ApplicationError

from sweep.activities.qa import _looks_like_test
from sweep.activities.skill_runner import _run_skill


ISSUE_REF_RE = re.compile(
    r"(?:closes|fixes|resolves|fix|close|resolve)\s+#(\d+)",
    re.IGNORECASE,
)


@dataclass
class SynthTestResult:
    """Outcome of one synth_test invocation, returned to qa_actor."""
    committed: bool
    commit_sha: str | None
    reason: str  # "committed", "punted:<why>", "no-issue-ref", "diff-empty"
    test_files: list[str]  # paths added to the working tree


def _git(worktree: str, *args: str) -> subprocess.CompletedProcess:
    """Run a git command in the worktree, capture output, no raise."""
    return subprocess.run(
        ["git", "-C", worktree, *args],
        capture_output=True, text=True,
    )


def _changed_files(worktree: str) -> list[str]:
    """Files modified by the fix branch vs origin/HEAD. Empty list on
    git failure (caller treats as 'nothing to synth a test for')."""
    r = _git(worktree, "diff", "--name-only", "origin/HEAD...")
    if r.returncode != 0:
        return []
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]


def _issue_number_from_pr_body(body: str) -> int | None:
    """First closes/fixes #N reference in the PR body. None if none."""
    m = ISSUE_REF_RE.search(body or "")
    return int(m.group(1)) if m else None


def _fetch_issue_text(repo: str, issue: int) -> str:
    """gh issue view → markdown blob. Empty string on failure."""
    r = subprocess.run(
        ["gh", "issue", "view", str(issue), "--repo", repo,
         "--json", "title,body,comments"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return ""
    import json
    try:
        d = json.loads(r.stdout)
    except json.JSONDecodeError:
        return ""
    parts = [f"# {d.get('title', '(no title)')}", "",
             d.get("body") or "(no body)"]
    for c in (d.get("comments") or [])[:5]:
        parts.append("")
        parts.append(f"## Comment by {c.get('author', {}).get('login', '?')}")
        parts.append(c.get("body") or "")
    return "\n".join(parts)


def _master_side_files(worktree: str, files: list[str]) -> dict[str, str]:
    """git show origin/HEAD:<file> for each file. Returns {path: content}.
    Files that don't exist on master (newly added by the fix) are skipped
    — those weren't modifications, so master has nothing to show."""
    out: dict[str, str] = {}
    for f in files:
        r = _git(worktree, "show", f"origin/HEAD:{f}")
        if r.returncode == 0:
            out[f] = r.stdout
    return out


def _sibling_test_examples(worktree: str, modified_files: list[str],
                            limit: int = 2) -> list[tuple[str, str]]:
    """Find up to `limit` existing test files near the modified files
    to use as convention examples. Walks up from each modified file's
    directory looking for sibling tests; falls back to repo-wide search."""
    seen: set[str] = set()
    examples: list[tuple[str, str]] = []

    candidate_dirs: list[Path] = []
    root = Path(worktree)
    for f in modified_files:
        p = (root / f).parent
        while p != root and p.exists():
            if p not in candidate_dirs:
                candidate_dirs.append(p)
            p = p.parent

    for d in candidate_dirs:
        if len(examples) >= limit:
            break
        try:
            for entry in d.iterdir():
                if len(examples) >= limit:
                    break
                if entry.is_file() and _looks_like_test(str(entry.name)):
                    key = str(entry.relative_to(root))
                    if key in seen:
                        continue
                    seen.add(key)
                    try:
                        examples.append((key, entry.read_text()[:6000]))
                    except OSError:
                        continue
        except OSError:
            continue

    if len(examples) < limit:
        for entry in root.rglob("*"):
            if len(examples) >= limit:
                break
            if not entry.is_file():
                continue
            if not _looks_like_test(str(entry.name)):
                continue
            key = str(entry.relative_to(root))
            if key in seen:
                continue
            if any(p in entry.parts for p in (".git", "node_modules", "vendor")):
                continue
            seen.add(key)
            try:
                examples.append((key, entry.read_text()[:6000]))
            except OSError:
                continue

    return examples


def _fix_already_has_tests(worktree: str) -> bool:
    """True if the fix branch already adds test files. Cheap check that
    prevents synth from running on PRs that don't need it."""
    return any(_looks_like_test(f) for f in _changed_files(worktree))


@activity.defn
async def synth_test_for_fix(repo: str, branch: str, worktree: str,
                              pr: int,
                              issue_number: int | None = None,
                              pr_body: str | None = None) -> dict:
    """Try to synthesize a regression test for the fix on `branch`.
    Returns a SynthTestResult-shaped dict the caller can inspect. Never
    raises on the punt path; only raises (non-retryable) if claude is
    missing or the skill subprocess itself fails to launch.

    Issue resolution order:
      1. issue_number kwarg (qa_actor already has this on the request)
      2. parse closes/fixes #N from pr_body
      3. punt as no-issue-ref
    """
    from sweep import observe

    if _fix_already_has_tests(worktree):
        return SynthTestResult(False, None, "diff-already-has-tests", []).__dict__

    issue_no = issue_number if issue_number else _issue_number_from_pr_body(pr_body or "")
    if issue_no is None:
        observe.event("synth_test_punted", repo=repo, pr=pr,
                      reason="no-issue-ref")
        return SynthTestResult(False, None, "no-issue-ref", []).__dict__

    issue_text = _fetch_issue_text(repo, issue_no)
    if not issue_text.strip():
        observe.event("synth_test_punted", repo=repo, pr=pr,
                      reason="issue-empty")
        return SynthTestResult(False, None, "issue-empty", []).__dict__

    files = _changed_files(worktree)
    if not files:
        observe.event("synth_test_punted", repo=repo, pr=pr,
                      reason="diff-empty")
        return SynthTestResult(False, None, "diff-empty", []).__dict__

    master_side = _master_side_files(worktree, files)
    examples = _sibling_test_examples(worktree, files)

    # Stage inputs in a temp dir; skill reads them by path. Keeps the
    # claude prompt short (no inline pastes of multi-KB source).
    with tempfile.TemporaryDirectory(prefix="synth-test-") as td:
        td_path = Path(td)
        issue_path = td_path / "issue.md"
        issue_path.write_text(issue_text)

        unfixed_dir = td_path / "unfixed"
        unfixed_dir.mkdir()
        for f, content in master_side.items():
            target = unfixed_dir / f
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)

        conv_dir = td_path / "test-conventions"
        conv_dir.mkdir()
        for path, content in examples:
            target = conv_dir / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)

        # Record HEAD so we can detect whether the skill committed.
        before = _git(worktree, "rev-parse", "HEAD").stdout.strip()

        slash_argv = [
            "/sweep:synth-test",
            f"--issue={issue_path}",
            f"--unfixed-root={unfixed_dir}",
            f"--conventions={conv_dir}",
            f"--worktree={worktree}",
            f"--repo={repo}",
        ]
        try:
            result = await _run_skill(slash_argv, label="synth_test",
                                      timeout_s=600, caller="qa")
        except ApplicationError:
            raise

        stdout_tail = result.get("stdout_tail", "")
        if "SYNTH_PUNTED" in stdout_tail:
            reason = stdout_tail.split("SYNTH_PUNTED:", 1)[-1].strip()[:200]
            observe.event("synth_test_punted", repo=repo, pr=pr,
                          reason=f"skill-punted:{reason}")
            return SynthTestResult(False, None,
                                    f"skill-punted:{reason}", []).__dict__

        after = _git(worktree, "rev-parse", "HEAD").stdout.strip()
        if before == after:
            observe.event("synth_test_punted", repo=repo, pr=pr,
                          reason="no-commit-made")
            return SynthTestResult(False, None, "no-commit-made", []).__dict__

        added = _git(worktree, "diff", "--name-only",
                     f"{before}..{after}").stdout
        test_files = [ln for ln in added.splitlines()
                      if ln.strip() and _looks_like_test(ln.strip())]
        if not test_files:
            observe.event("synth_test_punted", repo=repo, pr=pr,
                          reason="commit-has-no-tests")
            return SynthTestResult(False, after,
                                    "commit-has-no-tests", []).__dict__

        observe.event("synth_test_committed", repo=repo, pr=pr,
                      commit=after, test_files=test_files)
        return SynthTestResult(True, after, "committed", test_files).__dict__
