"""`sweep slop-offer` — the slop-filter outreach actor.

Dry-by-default outreach pipeline that pulls dep-pool candidates, runs
each through `offer-slop-filter`, and queues passing candidates to
~/.sweep/inbox/slop_offers_pending.jsonl for human review.

Subcommands:
  tick      walk dep-pool once, qualify candidates, queue passes
  review    list pending candidates in the inbox
  show <N>  print the Nth pending candidate's full rendered body
  post <N>  reserved — explicit per-candidate posting (manual `gh issue
            create` from `show` output is the v1 workflow)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer

HOME = Path.home()
DEP_POOL = HOME / ".sweep" / "bin" / "dep-pool"
OFFER = HOME / ".sweep" / "bin" / "offer-slop-filter"
INBOX = HOME / ".sweep" / "inbox" / "slop_offers_pending.jsonl"
WITHDRAW_INBOX = HOME / ".sweep" / "inbox" / "slop_withdrawals_pending.jsonl"

slop_offer_app = typer.Typer(
    help="Slop-filter outreach (dry-by-default; queues to operator inbox).",
    no_args_is_help=True,
)


def _pending() -> list[dict]:
    if not INBOX.exists():
        return []
    out: list[dict] = []
    for line in INBOX.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


@slop_offer_app.command("tick")
def tick(
    limit: int = typer.Option(10, "--limit", "-n",
                              help="Max candidates to consider this tick."),
    include: Optional[list[str]] = typer.Option(
        None, "--include",
        help="Extra owner/repo to walk (repeatable)."),
) -> None:
    """Pull dep-pool candidates and run each through offer-slop-filter.

    Each candidate that passes the gate ladder is queued to the operator
    inbox. Most candidates skip (low evidence, no maintainer pain, already
    offered, etc.) — that's the point. The filter ladder lives in
    offer-slop-filter; this command only orchestrates.
    """
    if not DEP_POOL.exists():
        typer.echo(f"ERR: {DEP_POOL} missing")
        raise typer.Exit(2)
    cmd = [str(DEP_POOL), "--limit", str(limit)]
    for x in include or []:
        cmd += ["--include", x]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=300, check=True)
    except subprocess.CalledProcessError as e:
        typer.echo(f"ERR: dep-pool failed: {e.stderr}")
        raise typer.Exit(2)
    except subprocess.TimeoutExpired:
        typer.echo("ERR: dep-pool timed out")
        raise typer.Exit(2)
    candidates = [r.strip() for r in out.stdout.splitlines() if r.strip()]
    typer.echo(f"dep-pool returned {len(candidates)} candidate repo(s)")
    queued = 0
    skipped = 0
    for repo in candidates:
        try:
            r = subprocess.run([str(OFFER), repo],
                               capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            typer.echo(f"  TIMEOUT: {repo}")
            continue
        last = (r.stdout or r.stderr).strip().splitlines()[-1:] or [""]
        line = last[0]
        if line.startswith("QUEUED:"):
            queued += 1
        else:
            skipped += 1
        typer.echo(f"  {line}")
    typer.echo(f"\n{queued} queued · {skipped} skipped → {INBOX}")


@slop_offer_app.command("review")
def review() -> None:
    """List pending candidates, newest first, with one-line summaries."""
    rows = _pending()
    if not rows:
        typer.echo(f"inbox empty: {INBOX}")
        return
    typer.echo(f"{len(rows)} pending · {INBOX}\n")
    for i, row in enumerate(rows):
        pain = " [pain]" if row.get("pain_example") else ""
        typer.echo(
            f"  {i:>3}  {row['repo']:<40}  "
            f"{row['evidence_count']}/{row['total_prs']} "
            f"({row['catch_pct']}%){pain}"
        )


@slop_offer_app.command("show")
def show(n: int = typer.Argument(..., help="Index from `review`.")) -> None:
    """Print the Nth pending candidate's full rendered body to stdout."""
    rows = _pending()
    if not 0 <= n < len(rows):
        typer.echo(f"ERR: index {n} out of range (0..{len(rows)-1})")
        raise typer.Exit(2)
    row = rows[n]
    typer.echo(f"# {row['repo']}  ({row['evidence_count']}/{row['total_prs']} = {row['catch_pct']}%)")
    typer.echo(f"# title: {row['title']}")
    if row.get("pain_example"):
        typer.echo(f"# pain:  {row['pain_example']}")
    typer.echo(f"# ts:    {row['ts']}\n")
    typer.echo(row["body"])


@slop_offer_app.command("withdrawals")
def withdrawals() -> None:
    """List pending withdrawal candidates (silent issues to close)."""
    if not WITHDRAW_INBOX.exists():
        typer.echo(f"inbox empty: {WITHDRAW_INBOX}")
        return
    rows = []
    for line in WITHDRAW_INBOX.read_text().splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    if not rows:
        typer.echo(f"inbox empty: {WITHDRAW_INBOX}")
        return
    typer.echo(f"{len(rows)} pending withdrawal(s) · {WITHDRAW_INBOX}\n")
    for i, row in enumerate(rows):
        typer.echo(f"  {i:>3}  {row['repo']}#{row['issue']}  {row['url']}")


if __name__ == "__main__":
    slop_offer_app()
