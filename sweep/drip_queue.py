"""Reader/appender for the per-repo drip queue.

State file: `~/.sweep/drip-queue/<owner>-<repo>.jsonl`, append-only. One
JSON object per line. The skill markdown ("/triage", "/drip") delegates
all reads/writes here so the schema lives in one place.

Schema (current, in active use):

  enqueue:
    {ts, repo, branch, issue, test_cmd, worktree, base, status:"queued",
     gates?, pr_title?, pr_body?, prompt?}

  pushed:
    {ts, repo, branch, issue, status:"pushed", pr_url}

  outcome:
    {ts, repo, branch, status:"merged"|"closed"|"rejected", ...}

Latest-line-per-branch is the read semantics. The skill receives the
latest state; older lines are history.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

QUEUE_DIR = Path.home() / ".sweep" / "drip-queue"


def _slug(repo: str) -> str:
    return repo.replace("/", "-")


def path_for(repo: str) -> Path:
    return QUEUE_DIR / f"{_slug(repo)}.jsonl"


def read(repo: str) -> list[dict]:
    """All entries in file order. Empty list if no file."""
    p = path_for(repo)
    if not p.exists():
        return []
    out: list[dict] = []
    for raw in p.read_text().splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return out


def latest_by_branch(repo: str) -> dict[str, dict]:
    """Last entry per branch — the current state of each item."""
    out: dict[str, dict] = {}
    for entry in read(repo):
        b = entry.get("branch")
        if not b:
            continue
        out[b] = entry
    return out


def append(repo: str, entry: dict) -> None:
    """Append one entry. Timestamps the entry if it doesn't carry one."""
    entry.setdefault("ts", dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
    entry.setdefault("repo", repo)
    p = path_for(repo)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps(entry, separators=(",", ":")) + "\n")


def enqueue(
    *,
    repo: str,
    branch: str,
    issue: int,
    test_cmd: str,
    base: str,
    worktree: str | None = None,
    prompt: str | None = None,
) -> dict:
    """Append a `status: "queued"` entry. Returns the entry written."""
    entry: dict = {
        "action": "enqueue",
        "repo": repo,
        "branch": branch,
        "issue": issue,
        "test_cmd": test_cmd,
        "base": base,
        "status": "queued",
    }
    if worktree:
        entry["worktree"] = worktree
    if prompt:
        entry["prompt"] = prompt
    append(repo, entry)
    return entry
