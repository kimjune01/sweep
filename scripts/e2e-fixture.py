#!/usr/bin/env python3
"""End-to-end fixture test — full qa pipeline against live GitHub + Haiku.

This is the production-shaped sibling of e2e-haiku.py: e2e-haiku proves
the substrate (llm_io + attestation log) works against the wire; this
proves the *pipeline* (qa_one_entry composing test_attestation +
codex_review + gemini_review + fuses) works against a real repo and a
real model.

Fixture repo: kimjune01/sweep-fixture. Bootstrap (one-time) creates it
with a buggy todo.py + tests. This script:

  1. Reset    — close open issues, hard-reset main to its root commit
  2. Inject   — open a known-title issue describing the bug
  3. Branch   — clone fresh, create fix-{N}, apply the deterministic fix
  4. Qa       — qa_one_entry with adversary_1 / _2 overridden to haiku
  5. Assert   — attestation rows, pinned head SHA, chain integrity,
                fuses pass for current SHA
  6. Tamper   — empty commit advances head; fuses must now blow
  7. Cleanup  — close the issue, drop the tempdir

Idempotent: scratch attestation DB at ~/.sweep/attestations/e2e-fixture.db,
cleaned up at the end. Operates on a fresh git tempdir per run.

Run:
  ANTHROPIC_API_KEY=sk-… uv run python scripts/e2e-fixture.py
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


FIXTURE_REPO = "kimjune01/sweep-fixture"
ISSUE_TITLE = "sweep-e2e: off-by-one in add_todo"
ISSUE_BODY = (
    "add_todo() appends N+1 items when called N times because the loop "
    "iterates over range(len(items) + 1). It should append once.\n\n"
    "Reproducer: `add_todo([], 'a')` returns `['a', 'a']` instead of `['a']`."
)

# Force adversary slots to haiku — the codex/gemini wrappers are still stubs.
os.environ["SWEEP_MODEL_ADVERSARY_1"] = "haiku"
os.environ["SWEEP_MODEL_ADVERSARY_2"] = "haiku"

# Redirect the attestation DB BEFORE importing sweep.
SCRATCH_DB = Path.home() / ".sweep" / "attestations" / "e2e-fixture.db"
SCRATCH_DB.parent.mkdir(parents=True, exist_ok=True)
SCRATCH_DB.unlink(missing_ok=True)

import sweep.attestations as att  # noqa: E402

att.DB_PATH = SCRATCH_DB

from sweep import fuses  # noqa: E402
from sweep.activities import qa  # noqa: E402
from sweep.types import QaOneEntryRequest  # noqa: E402


PASS = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"


def check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  {PASS} {label}{(' — ' + detail) if detail else ''}")
    else:
        print(f"  {FAIL} {label}{(' — ' + detail) if detail else ''}")
        sys.exit(1)


def stage(name: str) -> None:
    print()
    print(f"\033[1m▸ {name}\033[0m")


def run(cmd: list[str], cwd: str | None = None, check_: bool = True) -> subprocess.CompletedProcess:
    out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check_ and out.returncode != 0:
        print(f"FAIL {' '.join(cmd)}\nstderr: {out.stderr}", file=sys.stderr)
        sys.exit(1)
    return out


def root_sha(workdir: str) -> str:
    return run(["git", "rev-list", "--max-parents=0", "HEAD"], cwd=workdir).stdout.strip()


def head_sha(workdir: str) -> str:
    return run(["git", "rev-parse", "HEAD"], cwd=workdir).stdout.strip()


def default_branch() -> str:
    out = run(
        ["gh", "repo", "view", FIXTURE_REPO, "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name"],
    )
    return out.stdout.strip() or "main"


def close_open_issues() -> None:
    out = run(["gh", "issue", "list", "--repo", FIXTURE_REPO,
               "--state", "open", "--limit", "100", "--json", "number"])
    for row in json.loads(out.stdout or "[]"):
        # check_=False: a concurrent run may have already closed this issue
        # between the list and the close. Better to no-op than abort the
        # whole stage.
        run(["gh", "issue", "close", str(row["number"]),
             "--repo", FIXTURE_REPO], check_=False)


def close_open_prs() -> None:
    out = run(["gh", "pr", "list", "--repo", FIXTURE_REPO,
               "--state", "open", "--limit", "100", "--json", "number"])
    for row in json.loads(out.stdout or "[]"):
        run(["gh", "pr", "close", str(row["number"]),
             "--repo", FIXTURE_REPO], check_=False)


def apply_fix(workdir: str) -> None:
    todo = Path(workdir) / "todo.py"
    src = todo.read_text()
    fixed = src.replace(
        "for _ in range(len(items) + 1):\n        items.append(item)",
        "items.append(item)",
    )
    if fixed == src:
        print("FAIL: fix pattern didn't match — fixture todo.py format changed?", file=sys.stderr)
        sys.exit(1)
    todo.write_text(fixed)


async def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set — refusing to fake it.")
        return 1

    print(f"# fixture:    {FIXTURE_REPO}")
    print(f"# scratch db: {SCRATCH_DB}")
    print(f"# adversary_1/_2 → haiku (override)")

    branch = default_branch()
    workdir = tempfile.mkdtemp(prefix="sweep-fixture-")
    print(f"# workdir:    {workdir}")

    try:
        # --- stage 1: reset state ---
        stage("stage 1 — reset fixture state")
        close_open_prs()
        close_open_issues()
        run(["gh", "repo", "clone", FIXTURE_REPO, workdir, "--", "--quiet"])
        rsha = root_sha(workdir)
        run(["git", "reset", "--hard", rsha], cwd=workdir)
        run(["git", "push", "--force-with-lease", "origin", f"{branch}"], cwd=workdir)
        # Drop a non-pytest test driver into the worktree so qa.test_attestation
        # can run without external deps. It encodes the same contract as
        # test_todo.py: add_todo must append exactly once.
        Path(workdir, "runtest.py").write_text(
            "from todo import add_todo\n"
            "assert add_todo([], 'a') == ['a']\n"
            "assert add_todo(['a'], 'b') == ['a', 'b']\n"
            "print('ok')\n"
        )
        check("clone + reset to root commit", head_sha(workdir) == rsha,
              f"root {rsha[:12]}")
        check("no open issues", len(json.loads(run(
            ["gh", "issue", "list", "--repo", FIXTURE_REPO,
             "--state", "open", "--limit", "10", "--json", "number"]).stdout)) == 0)

        # --- stage 2: inject a known issue ---
        stage("stage 2 — inject known-title issue")
        out = run(["gh", "issue", "create", "--repo", FIXTURE_REPO,
                   "--title", ISSUE_TITLE, "--body", ISSUE_BODY])
        # `gh issue create` prints the URL on the last line.
        url = out.stdout.strip().splitlines()[-1]
        issue_n = int(url.rstrip("/").rsplit("/", 1)[-1])
        check("issue created", issue_n > 0, f"#{issue_n} @ {url}")

        # --- stage 3: branch + deterministic fix ---
        stage("stage 3 — fix branch")
        fix_branch = f"fix-{issue_n}"
        run(["git", "checkout", "-b", fix_branch], cwd=workdir)
        apply_fix(workdir)
        run(["git", "add", "todo.py"], cwd=workdir)
        run(["git", "-c", "commit.gpgsign=false", "commit",
             "-m", f"fix: stop appending N+1 (closes #{issue_n})"], cwd=workdir)
        fix_sha = head_sha(workdir)
        check("fix branch advanced HEAD", fix_sha != rsha, f"{fix_sha[:12]}")
        # Sanity: tests should now pass locally on the fix branch.
        run(["python3", "runtest.py"], cwd=workdir)
        check("runtest passes on fix branch", True)

        # --- stage 4: run qa_one_entry ---
        stage("stage 4 — qa_one_entry under haiku adversary")
        msg_id = f"e2e-fixture-{int(time.time())}-{issue_n}"
        req = QaOneEntryRequest(
            msg_id=msg_id,
            repo=FIXTURE_REPO,
            branch=fix_branch,
            worktree=workdir,
            test_cmd="python3 runtest.py",
            issue=issue_n,
        )
        result = await qa.qa_one_entry(req)
        check("qa returned a result", result is not None)
        check("msg_id matches request", result.msg_id == msg_id, result.msg_id)
        check("elapsed_seconds > 0", result.elapsed_seconds > 0,
              f"{result.elapsed_seconds:.2f}s")

        # --- stage 5: attestation + fuse assertions ---
        stage("stage 5 — attestations + fuses")
        # The qa wrapper checked out the default branch then the fix branch
        # during test_attestation. Re-checkout the fix branch so head_sha
        # below reflects the SHA the attestation pinned itself to.
        run(["git", "checkout", fix_branch], cwd=workdir)
        cur_head = head_sha(workdir)

        check("test attestation pinned to fix head",
              result.test_attestation.pinned_head_sha == cur_head,
              f"{(result.test_attestation.pinned_head_sha or '')[:12]} vs {cur_head[:12]}")
        check("codex attestation pinned to fix head",
              result.codex.pinned_head_sha == cur_head)
        check("gemini attestation pinned to fix head",
              result.gemini_last.pinned_head_sha == cur_head)
        check("codex receipt file exists",
              Path(result.codex.artifact_path).exists())
        check("gemini receipt file exists",
              Path(result.gemini_last.artifact_path).exists())
        check("codex provenance is haiku",
              "haiku" in result.codex.provenance, result.codex.provenance)
        check("gemini provenance is haiku-r1",
              result.gemini_last.provenance.startswith("haiku-r1"),
              result.gemini_last.provenance)

        # Under the haiku/haiku adversary override, codex and gemini send
        # identical (system, user, model, params) tuples, so the second
        # call is a cache hit and only one row lands in the log. The
        # provenance string above ("haiku-r1-cached") is the proof that
        # both gates traversed llm_io.call; we just don't double-bill.
        rows = att.for_msg(msg_id)
        check("at least one attestation row for msg_id", len(rows) >= 1,
              f"got {len(rows)}")
        check("every row has nonzero input_tokens",
              all(r.input_tokens > 0 for r in rows),
              f"{[r.input_tokens for r in rows]}")
        check("every row has a response_id",
              all(r.response_id for r in rows))
        check("every row tagged with repo",
              all(r.repo == FIXTURE_REPO for r in rows))
        check("gemini round was a cache hit (same prompt as codex)",
              "cached" in result.gemini_last.provenance,
              result.gemini_last.provenance)

        ok, count, broken = att.verify_chain()
        check("attestation chain verifies", ok, f"{count} rows checked")
        check("broken_rowid is None", broken is None)

        blown, reasons = fuses.check_qa_bundle(
            result.test_attestation, result.codex,
            result.gemini_first, result.gemini_last,
            current_head_sha=cur_head,
        )
        check("fuses pass for current head", not blown, "; ".join(reasons))

        # --- stage 6: tamper — advance head, fuses must blow ---
        stage("stage 6 — advance head, fuses blow")
        run(["git", "-c", "commit.gpgsign=false", "commit",
             "--allow-empty", "-m", "advance head"], cwd=workdir)
        new_head = head_sha(workdir)
        check("head SHA advanced", new_head != cur_head,
              f"{cur_head[:12]} → {new_head[:12]}")
        blown, reasons = fuses.check_qa_bundle(
            result.test_attestation, result.codex,
            result.gemini_first, result.gemini_last,
            current_head_sha=new_head,
        )
        check("fuses blow on head advance", blown)
        check("reason mentions head SHA change",
              any("head SHA changed" in r for r in reasons),
              reasons[0])

        # --- stage 7: cleanup ---
        stage("stage 7 — cleanup")
        close_open_issues()
        check("fixture issues closed", len(json.loads(run(
            ["gh", "issue", "list", "--repo", FIXTURE_REPO,
             "--state", "open", "--limit", "10", "--json", "number"]).stdout)) == 0)

        SCRATCH_DB.unlink(missing_ok=True)
        print()
        print(f"\033[32mall stages passed.\033[0m  fixture left clean.")
        return 0

    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
