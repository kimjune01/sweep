"""`sweep attest …` — inspect and verify the attestation log."""

from __future__ import annotations

import json
from dataclasses import asdict

import typer

from sweep import attestations


attest_app = typer.Typer(help="Attestation log — verify, inspect, audit", no_args_is_help=True)


@attest_app.command("verify")
def attest_verify() -> None:
    """Walk the chain, recompute every chain_hash, report status."""
    ok, count, broken_rowid = attestations.verify_chain()
    if ok:
        print(f"chain intact — {count} rows verified")
    else:
        print(f"CHAIN BROKEN at rowid {broken_rowid} (after {count} rows checked)")
        raise typer.Exit(2)


@attest_app.command("recent")
def attest_recent(
    limit: int = typer.Option(10, help="Number of most-recent calls to show"),
) -> None:
    """Show the last N calls."""
    rows = attestations.recent(limit)
    if not rows:
        print("# no calls recorded")
        return
    for r in rows:
        print(
            f"{r.ts[:19]}  {r.model_nick:7s} {r.provider:10s} "
            f"in={r.input_tokens:>5d}  out={r.output_tokens:>5d}  "
            f"key={r.key[:12]} chain={r.chain_hash[:12]} "
            f"msg={r.msg_id or '-'}"
        )


@attest_app.command("for-msg")
def attest_for_msg(msg_id: str) -> None:
    """All attestations recorded under one msg_id."""
    rows = attestations.for_msg(msg_id)
    if not rows:
        print(f"# no calls for msg_id={msg_id}")
        return
    for r in rows:
        print(
            f"{r.ts[:19]}  {r.model_nick:7s} in={r.input_tokens} out={r.output_tokens} "
            f"resp_id={r.response_id or '-'}  key={r.key[:12]}"
        )


@attest_app.command("tokens")
def attest_tokens() -> None:
    """Token usage summary by model."""
    summary = attestations.token_summary()
    if not summary:
        print("# no calls recorded")
        return
    print(json.dumps(summary, indent=2))


@attest_app.command("gh-cache")
def attest_gh_cache() -> None:
    """Cache stats for gh_io (rows per endpoint, live vs expired)."""
    from sweep import gh_io
    stats = gh_io.cache_stats()
    if not stats:
        print("# gh cache empty")
        return
    print(json.dumps(stats, indent=2))


@attest_app.command("gh-purge")
def attest_gh_purge() -> None:
    """Delete expired gh cache rows."""
    from sweep import gh_io
    n = gh_io.purge_expired()
    print(f"purged {n} expired rows")


@attest_app.command("backfill")
def attest_backfill(
    repo: str = typer.Option(..., help="owner/repo (e.g. wild-linker/wild)"),
    pr: int = typer.Option(..., help="PR number — enables the amend fan-out"),
    branch: str = typer.Option(None, help="Fix branch name. If omitted, looked up from the PR via gh."),
    worktree: str = typer.Option(None, help="Path to an existing local checkout with the fix branch + default branch reachable. If omitted, ensure_worktree clones/fetches (will fail on fork branches)."),
    sender: str = typer.Option("backfill", help="Sender tag recorded on the card"),
) -> None:
    """Kick an attest card outside the investigate pipeline.

    Attest produces a triple in our sweep repo and (when msg.pr is set)
    fans out to amend. Neither step touches the maintainer's branch
    destructively — attestation files live in OUR repo and amend's
    splice is a single-line PR-body append. So the per-repo policy
    gates (human-only.txt etc.) do not apply here; this entrypoint
    bypasses investigate, which is where those gates live.

    Use when:
      - the repo is operator-only and the natural investigate→attest
        path is blocked at the policy gate
      - you want to backfill an existing PR (no investigate work needed)
      - the fix branch lives on a fork the substrate's clone can't
        reach (supply --worktree to a local checkout that has it)
    """
    import asyncio
    from sweep import gh_io
    from sweep.activities.attest import kick_attest_card

    if branch is None:
        meta = gh_io.pr_view(repo, pr, fields="headRefName")
        branch = (meta or {}).get("headRefName") if isinstance(meta, dict) else None
        if not branch:
            raise typer.Exit(f"could not resolve branch for {repo}#{pr}")

    payload: dict = {}
    if worktree:
        from pathlib import Path
        if not Path(worktree).is_dir():
            raise typer.Exit(f"worktree {worktree!r} does not exist")
        payload["worktree"] = worktree

    async def _kick():
        return await kick_attest_card(
            repo=repo, branch=branch, pr=pr,
            sender=sender, payload=payload,
        )

    wf_id = asyncio.run(_kick())
    if wf_id is None:
        print(f"deposited card on attest.jsonl but signal failed "
              f"(actor unwired or temporal down). The card persists "
              f"and will be drained on next worker start.")
    else:
        print(f"kicked attest for {repo}#{pr} on {branch}")
        if worktree:
            print(f"  using local worktree: {worktree}")
        print(f"  watch: sweep observe events --kind attest_routed")
        print(f"  or:   tail -f ~/.sweep/events.jsonl | grep {repo}")
