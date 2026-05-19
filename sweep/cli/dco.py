"""`sweep dco` — manage DCO-signoff pushes.

The dco-batch worker rewrites commits with Signed-off-by lines and
deposits a `dco-pushready` card into human.jsonl. The force-push is
intentionally operator-gated (rewrites published PR history). This
CLI is the operator's hand on that gate: list pending pushes, run
them as a batch, and verify-and-ack after the fork shows the new
SHA.

Why not auto-push: per the maintainer-respect register, force-pushes
to a PR branch fire a maintainer notification. We want those bunched
into deliberate operator actions, not slipping out of a heartbeat.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table


dco_app = typer.Typer(help="DCO-signoff push management.", invoke_without_command=False)
console = Console()


HUMAN_INBOX = Path.home() / ".sweep" / "inbox" / "human.jsonl"
ACKS = Path.home() / ".sweep" / "inbox" / "_acks.jsonl"


def _pending() -> list[dict]:
    """Return queued dco-pushready cards (unacked, sender=dco-batch)."""
    from sweep.inbox_state import inbox_states
    s = inbox_states("human")
    out = []
    for m in s["queued"]:
        if m.get("sender") != "dco-batch":
            continue
        out.append(m)
    return out


def _parse_card(m: dict) -> dict | None:
    """Extract {repo, pr, branch, worktree, push_url} from a card.
    Returns None if any required field is missing."""
    payload = m.get("payload") or {}
    repo = m.get("repo")
    pr = m.get("pr")
    branch = m.get("branch") or payload.get("branch")
    push_cmd = payload.get("push_cmd") or ""
    push_url = payload.get("push_url") or ""

    # Extract worktree + fork URL from the push_cmd if not in payload.
    worktree = payload.get("worktree")
    fork_url = None
    if push_cmd and "cd " in push_cmd and "git push" in push_cmd:
        try:
            cd_part, push_part = push_cmd.split(" && ", 1)
            worktree = cd_part.removeprefix("cd ").strip()
            parts = push_part.split()
            # ['git', 'push', '--force', '<url>', 'HEAD:<branch>']
            for i, p in enumerate(parts):
                if p.endswith(".git"):
                    fork_url = p
                    break
        except Exception:
            pass

    if not (repo and pr and branch and worktree and fork_url):
        return None
    return {
        "msg_id": m.get("msg_id"),
        "repo": repo,
        "pr": int(pr),
        "branch": branch,
        "worktree": worktree,
        "fork_url": fork_url,
        "upstream_url": push_url or f"git@github.com:{repo}.git",
    }


@dco_app.command("list")
def list_cmd() -> None:
    """List pending dco-pushready cards."""
    cards = _pending()
    if not cards:
        console.print("[green]No pending dco-pushready cards.[/green]")
        return
    t = Table(title=f"{len(cards)} pending DCO pushes")
    t.add_column("PR")
    t.add_column("branch")
    t.add_column("worktree (truncated)")
    for m in cards:
        parsed = _parse_card(m)
        if not parsed:
            t.add_row(f"{m.get('repo')}#{m.get('pr')}", "(malformed card)", "")
            continue
        wt = parsed["worktree"].replace(str(Path.home()), "~")
        t.add_row(f"{parsed['repo']}#{parsed['pr']}", parsed["branch"], wt)
    console.print(t)


@dco_app.command("push")
def push_cmd(
    dry_run: bool = typer.Option(False, "--dry-run", help="Print commands but don't run."),
    only: str = typer.Option("", "--only", help="Match repo or PR number; push only matching cards."),
) -> None:
    """Force-push every pending dco-pushready branch to its fork.

    Runs each `git push --force` directly via subprocess (no shell),
    so zsh aliases/functions can't strip flags. Does NOT ack the
    human cards — run `sweep dco verify` after, which acks based on
    fork SHA matching local SHA.
    """
    cards = _pending()
    if not cards:
        console.print("[green]Nothing to push.[/green]")
        return

    if only:
        cards = [m for m in cards
                 if only in (m.get("repo","") or "")
                 or only == str(m.get("pr",""))]
        if not cards:
            console.print(f"[yellow]No pending cards match {only!r}.[/yellow]")
            return

    for m in cards:
        parsed = _parse_card(m)
        if not parsed:
            console.print(f"[red]skip (malformed):[/red] {m.get('repo')}#{m.get('pr')}")
            continue
        args = ["git", "-C", parsed["worktree"], "push", "--force",
                parsed["fork_url"], f"HEAD:{parsed['branch']}"]
        console.print(f"[cyan]→[/cyan] {parsed['repo']}#{parsed['pr']} "
                      f"({parsed['branch']})")
        if dry_run:
            console.print(f"   [dim]{' '.join(args)}[/dim]")
            continue
        try:
            r = subprocess.run(args, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            console.print(f"   [red]TIMEOUT[/red]")
            continue
        if r.returncode == 0:
            console.print(f"   [green]pushed[/green]")
        else:
            console.print(f"   [red]failed rc={r.returncode}[/red]")
            console.print(f"   [dim]{(r.stderr or r.stdout)[:300]}[/dim]")


def auto_run() -> dict:
    """One-shot push-then-verify for every pending dco-pushready card.
    Called from the metronome cadence target. Returns
    {pushed, push_failed, acked, sha_mismatch}. Failures stay queued —
    the operator sees them in `sweep dco list` and can investigate.

    Rationale for automating: DCO sign-off is the most expected force-
    push class (the contributor certifies the commit's provenance, by
    definition rewriting history). The maintainer-facing surprise
    surface is near zero. Other force-pushes (squash, rebase against
    moved master) stay operator-gated."""
    import datetime as dt
    pushed = 0
    push_failed = 0
    acked = 0
    sha_mismatch = 0
    cards = _pending()
    for m in cards:
        parsed = _parse_card(m)
        if not parsed:
            continue
        # Push.
        args = ["git", "-C", parsed["worktree"], "push", "--force",
                parsed["fork_url"], f"HEAD:{parsed['branch']}"]
        try:
            r = subprocess.run(args, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            push_failed += 1
            continue
        if r.returncode != 0:
            push_failed += 1
            continue
        pushed += 1
    # Verify + ack via SHA compare.
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
    new_acks: list[str] = []
    for m in cards:
        parsed = _parse_card(m)
        if not parsed:
            continue
        try:
            stem = parsed["fork_url"].removeprefix("https://github.com/").removeprefix("git@github.com:").removesuffix(".git")
            fork_owner, fork_repo = stem.split("/", 1)
        except Exception:
            continue
        local = subprocess.run(
            ["git", "-C", parsed["worktree"], "rev-parse", "HEAD"],
            capture_output=True, text=True,
        )
        local_sha = (local.stdout or "").strip()
        if not local_sha:
            continue
        remote = subprocess.run(
            ["gh", "api", f"repos/{fork_owner}/{fork_repo}/git/refs/heads/{parsed['branch']}",
             "--jq", ".object.sha"],
            capture_output=True, text=True,
        )
        if remote.returncode != 0:
            continue
        remote_sha = (remote.stdout or "").strip()
        if remote_sha == local_sha:
            new_acks.append(json.dumps({
                "msg_id": parsed["msg_id"], "ts": now_iso, "from": "dco-auto",
                "outcome": f"pushed-to-fork sha={local_sha[:8]}",
            }))
            acked += 1
        else:
            sha_mismatch += 1
    if new_acks:
        ACKS.parent.mkdir(parents=True, exist_ok=True)
        with open(ACKS, "a") as f:
            for line in new_acks:
                f.write(line + "\n")
    return {"pushed": pushed, "push_failed": push_failed,
            "acked": acked, "sha_mismatch": sha_mismatch,
            "pending": len(cards)}


@dco_app.command("verify")
def verify_cmd(
    ack: bool = typer.Option(True, "--ack/--no-ack",
                              help="Ack human cards whose fork SHA matches local."),
) -> None:
    """Check which branches are pushed (compare local HEAD vs fork
    branch SHA via gh api). When --ack, write an ack record for each
    matching card, decrementing the human inbox count to reflect what's
    actually pushed."""
    import datetime as dt
    cards = _pending()
    if not cards:
        console.print("[green]No pending dco-pushready cards.[/green]")
        return
    new_acks: list[str] = []
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
    for m in cards:
        parsed = _parse_card(m)
        if not parsed:
            continue
        repo = parsed["repo"]
        pr = parsed["pr"]
        branch = parsed["branch"]
        worktree = parsed["worktree"]
        # Owner of the fork: derive from fork_url
        fork = parsed["fork_url"]
        # https://github.com/<owner>/<repo>.git
        try:
            stem = fork.removeprefix("https://github.com/").removeprefix("git@github.com:")
            stem = stem.removesuffix(".git")
            fork_owner, fork_repo = stem.split("/", 1)
        except Exception:
            console.print(f"[red]?[/red] {repo}#{pr} fork url parse failed: {fork}")
            continue
        # Local SHA on the worktree's current HEAD.
        local = subprocess.run(
            ["git", "-C", worktree, "rev-parse", "HEAD"],
            capture_output=True, text=True,
        )
        local_sha = (local.stdout or "").strip()
        if not local_sha:
            console.print(f"[red]?[/red] {repo}#{pr} local HEAD unknown")
            continue
        # Remote SHA on the fork's branch.
        remote = subprocess.run(
            ["gh", "api", f"repos/{fork_owner}/{fork_repo}/git/refs/heads/{branch}",
             "--jq", ".object.sha"],
            capture_output=True, text=True,
        )
        if remote.returncode != 0:
            console.print(f"[yellow]✗[/yellow] {repo}#{pr} fork has no {branch}")
            continue
        remote_sha = (remote.stdout or "").strip()
        match = (remote_sha == local_sha)
        glyph = "[green]✓[/green]" if match else "[yellow]✗[/yellow]"
        console.print(f"{glyph} {repo}#{pr} local={local_sha[:8]} fork={remote_sha[:8]}")
        if match and ack:
            new_acks.append(json.dumps({
                "msg_id": parsed["msg_id"], "ts": now_iso, "from": "dco-verify",
                "outcome": f"pushed-to-fork sha={local_sha[:8]}",
            }))
    if new_acks:
        ACKS.parent.mkdir(parents=True, exist_ok=True)
        with open(ACKS, "a") as f:
            for line in new_acks:
                f.write(line + "\n")
        console.print(f"\n[green]acked {len(new_acks)} pushed card(s)[/green]")
