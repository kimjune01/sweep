"""`sweep retro …` — inspect + manage the SOAP one-pager pager.

Writes are owned by the /retro skill (drafts SOAP prose by folding
events). This CLI is the human-side: list pending pagers, peek at one,
discard after Attending. Discard is the "I've Consolidated this — git
log carries the receipt" signal.
"""

from __future__ import annotations

import typer

from sweep import retro_state


retro_app = typer.Typer(help="Retro pager — SOAP one-pagers", no_args_is_help=True)


@retro_app.command("list")
def retro_list() -> None:
    """Pending pagers, oldest first. Cap is 2; pipeline halts at the cap."""
    files = retro_state.list_retros()
    if not files:
        print("# no pending retros")
        return
    for r in files:
        print(f"{r.written_at.isoformat(timespec='seconds')}  {r.name}")
    if retro_state.is_halted():
        print(f"\n# PIPELINE HALTED — cap {retro_state.RETRO_CAP} reached. "
              f"Discard one to resume.")


@retro_app.command("status")
def retro_status() -> None:
    """One-line summary: count + halt state."""
    n = len(retro_state.list_retros())
    state = "HALTED" if retro_state.is_halted() else "running"
    print(f"retros: {n}/{retro_state.RETRO_CAP}  pipeline: {state}")


@retro_app.command("show")
def retro_show(slug: str = typer.Argument(..., help="retro slug (filename without .md)")) -> None:
    """Print one retro to stdout."""
    path = retro_state.RETROS / f"{slug}.md"
    if not path.exists():
        raise typer.BadParameter(f"no such retro: {slug}")
    print(path.read_text())


@retro_app.command("discard")
def retro_discard(slug: str = typer.Argument(..., help="retro slug (filename without .md)")) -> None:
    """Delete one retro by slug. The signal to the pipeline that you've
    Attended — any actions worth taking should already be in git history."""
    ok = retro_state.discard_retro(slug)
    if not ok:
        raise typer.BadParameter(f"no such retro: {slug}")
    print(f"discarded {slug}")
    if not retro_state.is_halted():
        n = len(retro_state.list_retros())
        print(f"pipeline running ({n}/{retro_state.RETRO_CAP})")
