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
