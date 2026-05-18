"""`sweep cerify …` — single-activity contract verifier.

Runs an activity in an isolated sandbox (no temporal, no real inbox
writes, no remote mutations), captures returned value + recorded
side-effects + wall time, then re-runs and checks the monoidal
contract (second run identical to first).
"""

from __future__ import annotations

import datetime as dt

import typer

from sweep import cerify as _cerify
from sweep.types import Message


cerify_app = typer.Typer(help="Cerify — verify a single activity in isolation",
                          no_args_is_help=True)


def _msg(*, sender: str, intent: str, repo: str, branch: str | None,
         pr: int | None, payload: dict) -> Message:
    ts = dt.datetime.now(dt.timezone.utc)
    slug = repo.replace("/", "-")
    suffix = f"-{pr}" if pr else (f"-{branch}" if branch else "")
    return Message(
        msg_id=f"cerify-{ts.strftime('%Y%m%dT%H%M%S')}-{slug}{suffix}",
        sender=sender, intent=intent, repo=repo, pr=pr, branch=branch,
        payload=payload, ts=ts.isoformat(), ledger=[],
    )


@cerify_app.command("attest")
def cerify_attest(
    repo: str = typer.Option(..., help="owner/repo"),
    branch: str = typer.Option(..., help="fix branch name"),
    pr: int | None = typer.Option(None, help="PR number (enables ci-regression pre-flight + amend fan-out check)"),
) -> None:
    """Cerify attest_cycle. Pre-flight short-circuits if PR is set and
    the regression check fails — that path is the cheapest to verify
    and the one we wired most recently."""
    from sweep.activities.attest import attest_cycle

    msg = _msg(sender="cerify", intent="attest", repo=repo,
               branch=branch, pr=pr, payload={})
    raise typer.Exit(_cerify.run(attest_cycle, msg))


@cerify_app.command("amend")
def cerify_amend(
    repo: str = typer.Option(..., help="owner/repo"),
    pr: int = typer.Option(..., help="PR number"),
    kind: str = typer.Option("attestation", help="amend handler kind"),
    snippet: str = typer.Option(..., help="markdown block to splice"),
    mutate: bool = typer.Option(False, "--mutate/--no-mutate",
                                help="Actually run gh pr edit (default: stub the mutation)"),
) -> None:
    """Cerify amend_cycle. By default the gh pr edit call is stubbed;
    --mutate runs it for real (useful when the splice is what you want
    to verify end-to-end)."""
    from sweep.activities.amend import amend_cycle

    msg = _msg(sender="cerify", intent=f"amend-{kind}", repo=repo,
               branch=None, pr=pr,
               payload={"kind": kind, "attestation_links_md": snippet})
    raise typer.Exit(_cerify.run(amend_cycle, msg, stub_mutations=not mutate))
