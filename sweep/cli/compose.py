"""`sweep compose` — backfill / inspect the compose-owned PR body section.

Compose owns a marker-pair section in the PR body that gets spliced in
idempotently. `backfill` deposits a card on compose.jsonl so the actor
processes it just like a card arriving via the production lane (after
attest pass). Useful for re-running compose against existing PRs once
the renderer template changes — re-runs converge.
"""

from __future__ import annotations

import typer

compose_app = typer.Typer(
    help="Compose — body writer / amender for PR bodies",
    no_args_is_help=True,
)


@compose_app.command("backfill")
def compose_backfill(
    repo: str = typer.Option(..., help="owner/repo"),
    pr: int = typer.Option(..., help="PR number (existing PR; splice path)"),
    attestation_hash: str = typer.Option(
        ..., "--attestation-hash", "-a",
        help="Attestation hash to embed in the compose block. Look up via "
             "`sweep attest recent` or the prior attest_routed event.",
    ),
    branch: str = typer.Option(
        None, help="PR head branch. Looked up from gh if omitted."),
    sender: str = typer.Option(
        "backfill", help="Sender tag recorded on the card"),
) -> None:
    """Kick a compose card to splice the compose-managed section into
    an existing PR's body. Idempotent — re-runs that produce the same
    rendered block are a noop_unchanged.
    """
    import asyncio
    from sweep import gh_io
    from sweep.activities.compose import kick_compose_card

    if branch is None:
        meta = gh_io.pr_view(repo, pr, fields="headRefName")
        branch = (meta or {}).get("headRefName") if isinstance(meta, dict) else None
        if not branch:
            raise typer.Exit(f"could not resolve branch for {repo}#{pr}")

    async def _kick() -> str | None:
        return await kick_compose_card(
            repo=repo, branch=branch, pr=pr,
            sender=sender, attestation_hash=attestation_hash,
        )

    wf_id = asyncio.run(_kick())
    if wf_id is None:
        print("deposited card on compose.jsonl but signal failed "
              "(actor unwired or temporal down). The card persists "
              "and will be drained on next worker start.")
    else:
        print(f"kicked compose for {repo}#{pr} on {branch}")
        print(f"  attestation: {attestation_hash[:12]}…")
        print(f"  watch: sweep observe events --kind compose_applied")
        print(f"  or:   tail -f ~/.sweep/events.jsonl | grep {repo}")
