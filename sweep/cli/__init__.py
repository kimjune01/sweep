"""Sweep CLI — Typer subcommands grouped by actor.

Each subgroup lives in its own module:
  cli/qa.py        — qa test/codex/gemini/full, qa actor signal/status/clear
  cli/sift.py      — sift sweep + cursor (legacy escape hatch)
  cli/inbox.py     — inbox inspector
  cli/attest.py    — attestation log + gh-cache stats
  cli/observe.py   — counters, events, cursor for retro
  cli/cockpit.py   — factory-floor cockpit (status + flow + table)
  cli/lanes.py     — swim lanes (per-station PR detail)
  cli/leakdog.py   — funnel-balance accounting across station interfaces
  cli/drip.py      — drip queue list + enqueue
  cli/missing.py   — `sweep missing` wishlist (unknown-call log)

The console-script entry point is `sweep.cli:app` (also re-exported as
`sweep.client:app` for backward compatibility).
"""

from __future__ import annotations

import sys

import click
import typer

from sweep import missing_calls, models as _models
from sweep.cli import cockpit as _cockpit
from sweep.cli import feed as _feed
from sweep.cli import hygraph as _hygraph
from sweep.cli import lanes as _lanes
from sweep.cli import leakdog as _leakdog
from sweep.cli import claim as _claim
from sweep.cli import investigate as _investigate
from sweep.cli import missing as _missing
from sweep.cli import tui as _tui
from sweep.cli import waste as _waste
from sweep.cli import wish as _wish
from sweep.cli import pr as _pr
from sweep.cli import project_info as _project_info
from sweep.cli.andon import andon_app
from sweep.cli.attest import attest_app
from sweep.cli.broom import broom_app
from sweep.cli.cache import cache_app
from sweep.cli.compose import compose_app
from sweep.cli.dco import dco_app
from sweep.cli.evict import evict_app
from sweep.cli.cerify import cerify_app
from sweep.cli.control import dry_app, pause_app
from sweep.cli.lifecycle import down_app, status_app, up_app
from sweep.cli.drip import drip_app
from sweep.cli.inbox import inbox_app
from sweep.cli.observe import observe_app
from sweep.cli.sift import sift_app
from sweep.cli.qa import qa_app
from sweep.cli.retro import retro_app
from sweep.cli.slop_offer import slop_offer_app
from sweep.cli.comment_issue import comment_issue_app
from sweep.cli.file_issue import file_issue_app
from sweep.cli.hold_issue import hold_issue_app


app = typer.Typer(
    help="Sweep — Temporal-supervised PR pipeline",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
app.add_typer(andon_app, name="andon")
app.add_typer(qa_app, name="qa")
app.add_typer(sift_app, name="sift")
app.add_typer(inbox_app, name="inbox")
app.add_typer(attest_app, name="attest")
app.add_typer(broom_app, name="broom")
app.add_typer(cache_app, name="cache")
app.add_typer(compose_app, name="compose")
app.add_typer(dco_app, name="dco")
app.add_typer(evict_app, name="evict")
app.add_typer(cerify_app, name="cerify")
app.add_typer(observe_app, name="observe")
app.add_typer(retro_app, name="retro")
app.add_typer(slop_offer_app, name="slop-offer")
app.add_typer(comment_issue_app, name="comment-issue")
app.add_typer(file_issue_app, name="file-issue")
app.add_typer(hold_issue_app, name="hold-issue")
app.add_typer(drip_app, name="drip")
app.add_typer(dry_app, name="dry")
app.add_typer(pause_app, name="pause")
app.add_typer(up_app, name="up")
app.add_typer(down_app, name="down")
app.add_typer(status_app, name="status")
_cockpit.register(app)
_feed.register(app)
_hygraph.register(app)
_lanes.register(app)
_leakdog.register(app)
_pr.register(app)
_project_info.register(app)
_claim.register(app)
_investigate.register(app)
_missing.register(app)
_tui.register(app)
_waste.register(app)
_wish.register(app)


@app.command("models")
def models_cmd() -> None:
    """Show model registry, role defaults, adversary cascade."""
    print(_models.describe())


def main() -> None:
    """Run the Typer app, logging unknown-call failures to the
    missing-calls wishlist. Re-raises so the user / agent still sees
    the standard error output and exit code."""
    try:
        app(standalone_mode=False)
    except click.exceptions.UsageError as e:
        # Typer/click raises UsageError for unknown commands ("No such
        # command 'foo'.") and unknown options ("No such option: --bar").
        # Either is a wishlist signal — an agent reached for it.
        try:
            missing_calls.record(sys.argv[1:], str(e))
        except Exception:
            pass  # never let logging failure mask the real error
        # Emit the original error message + exit code the way click would.
        e.show()
        sys.exit(e.exit_code if e.exit_code is not None else 2)
    except click.exceptions.Abort:
        sys.exit(1)
    except SystemExit:
        raise


if __name__ == "__main__":
    main()
