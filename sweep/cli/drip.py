"""`sweep drip …` — read and write the per-repo drip queue.

Two subcommands today (the certain ones — pottery-shaped, more to come
as agents demand them via the missing-calls log):

  sweep drip list --repo OWNER/REPO
  sweep drip enqueue --repo OWNER/REPO --branch ... --issue N --test-cmd ... --base SHA

Reads/writes go through sweep.drip_queue. The skill markdown never
touches the jsonl directly.
"""

from __future__ import annotations

import json
from typing import Optional

import typer

from sweep import drip_queue

drip_app = typer.Typer(help="Per-repo drip queue", no_args_is_help=True)


@drip_app.command("list")
def drip_list(
    repo: str = typer.Option(..., help="owner/repo"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON (default: human)"),
) -> None:
    """Show the current state of each branch in the queue (latest line wins)."""
    latest = drip_queue.latest_by_branch(repo)
    if json_out:
        print(json.dumps(list(latest.values()), indent=2))
        return
    if not latest:
        print(f"# no entries for {repo}")
        return
    print(f"# {repo} — {len(latest)} entries")
    for branch, entry in sorted(latest.items()):
        status = entry.get("status", "?")
        issue = entry.get("issue", "-")
        pr = entry.get("pr_url", "")
        suffix = f"  {pr}" if pr else ""
        print(f"  [{status:10s}] {branch}  (issue #{issue}){suffix}")


@drip_app.command("enqueue")
def drip_enqueue(
    repo: str = typer.Option(..., help="owner/repo"),
    branch: str = typer.Option(..., help="fix branch name (must already exist locally)"),
    issue: int = typer.Option(..., help="issue number this fix addresses"),
    test_cmd: str = typer.Option(..., "--test-cmd", help="command that fails on master, passes on fix"),
    base: str = typer.Option(..., help="base commit SHA (the master sha the branch forked from)"),
    worktree: Optional[str] = typer.Option(None, help="local worktree path (optional)"),
    prompt_file: Optional[str] = typer.Option(
        None, "--prompt-file",
        help="path to a file containing the natural-language prompt the harness should hand the next stage",
    ),
) -> None:
    """Append a `status: queued` entry to the drip queue.

    Idempotency: re-enqueuing the same branch appends another line. The
    latest line wins on read, so re-running this with updated args is the
    way to revise an entry. (No silent dedup — every reach is logged.)
    """
    prompt: Optional[str] = None
    if prompt_file:
        from pathlib import Path
        p = Path(prompt_file)
        if not p.exists():
            raise typer.BadParameter(f"prompt file not found: {prompt_file}")
        prompt = p.read_text()
    entry = drip_queue.enqueue(
        repo=repo,
        branch=branch,
        issue=issue,
        test_cmd=test_cmd,
        base=base,
        worktree=worktree,
        prompt=prompt,
    )
    print(json.dumps(entry, separators=(",", ":")))
