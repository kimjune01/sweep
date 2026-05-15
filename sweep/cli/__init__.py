"""Sweep CLI — Typer subcommands grouped by actor.

Each subgroup lives in its own module:
  cli/qa.py        — qa test/codex/gemini/full, qa actor signal/status/clear
  cli/pr_state.py  — pr-state classify / run / scan / route / workflow
  cli/prospect.py  — prospect sweep + cursor
  cli/inbox.py     — inbox inspector
  cli/attest.py    — attestation log + gh-cache stats
  cli/observe.py   — counters, events, cursor for retro
  cli/floor.py     — factory-floor cockpit (status + flow + table)
  cli/kanban.py    — kanban swim lanes (per-station PR detail)

The console-script entry point is `sweep.cli:app` (also re-exported as
`sweep.client:app` for backward compatibility).
"""

from __future__ import annotations

import typer

from sweep import models as _models
from sweep.cli import floor as _floor
from sweep.cli import kanban as _kanban
from sweep.cli import pr as _pr
from sweep.cli.attest import attest_app
from sweep.cli.inbox import inbox_app
from sweep.cli.observe import observe_app
from sweep.cli.pr_state import pr_state_app
from sweep.cli.prospect import prospect_app
from sweep.cli.qa import qa_app
from sweep.cli.retro import retro_app


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
app.add_typer(observe_app, name="observe")
app.add_typer(retro_app, name="retro")
_floor.register(app)
_kanban.register(app)
_pr.register(app)


@app.command("models")
def models_cmd() -> None:
    """Show model registry, role defaults, adversary cascade."""
    print(_models.describe())


if __name__ == "__main__":
    app()
