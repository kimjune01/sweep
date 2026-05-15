"""Sweep CLI — Typer subcommands grouped by actor.

Each subgroup lives in its own module:
  cli/qa.py        — qa test/codex/gemini/full, qa actor signal/status/clear
  cli/pr_state.py  — pr-state classify/run/workflow
  cli/inbox.py     — inbox inspector
  cli/punch.py     — punch (cockpit + outcomes)

The console-script entry point is `sweep.cli:app` (also re-exported as
`sweep.client:app` for backward compatibility).
"""

from __future__ import annotations

import typer

from sweep import models as _models
from sweep.cli import board as _board
from sweep.cli import punch as _punch
from sweep.cli.attest import attest_app
from sweep.cli.inbox import inbox_app
from sweep.cli.pr_state import pr_state_app
from sweep.cli.prospect import prospect_app
from sweep.cli.qa import qa_app


app = typer.Typer(
    help="Sweep — Temporal-supervised PR pipeline",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
app.add_typer(qa_app, name="qa")
app.add_typer(pr_state_app, name="pr-state")
app.add_typer(prospect_app, name="prospect")
app.add_typer(inbox_app, name="inbox")
app.add_typer(attest_app, name="attest")
_punch.register(app)
_board.register(app)


@app.command("models")
def models_cmd() -> None:
    """Show model registry, role defaults, adversary cascade."""
    print(_models.describe())


if __name__ == "__main__":
    app()
