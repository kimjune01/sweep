"""`sweep claim` — post the first-mover claim comment on an issue.

Invoked from /investigate at the moment its pushout converges. Honors
per-repo `retro_param claim_after_investigate` (default false) and the
global `dry` flag. Idempotent at the activity level — the operator
opts in per repo.
"""

from __future__ import annotations

import asyncio

import typer

from sweep.activities.claim import claim_issue


claim_app = typer.Typer(help="Post a 'looking at this' claim on an issue.",
                        no_args_is_help=True, invoke_without_command=True)


@claim_app.callback(invoke_without_command=True)
def claim(
    ref: str = typer.Argument(..., help="owner/repo#N"),
    summary: str = typer.Option(..., "--summary", "-s",
                                help="One-sentence fix-shape hypothesis"),
) -> None:
    """Wraps the claim_issue activity for shell invocation."""
    if "#" not in ref:
        raise typer.BadParameter(f"ref must be owner/repo#N, got {ref!r}")
    repo, issue_s = ref.rsplit("#", 1)
    try:
        issue = int(issue_s)
    except ValueError:
        raise typer.BadParameter(f"issue must be int, got {issue_s!r}")
    result = asyncio.run(claim_issue(repo, issue, summary))
    typer.echo(result.get("state"))
    if result.get("state") == "claimed" and result.get("comment_url"):
        typer.echo(result["comment_url"])


def register(app: typer.Typer) -> None:
    app.add_typer(claim_app, name="claim")
