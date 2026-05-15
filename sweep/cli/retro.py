"""`sweep retro …` — inspect + manage the SOAP one-pager pager.

Writes are owned by the /retro skill (drafts SOAP prose by folding
events). This CLI is the human-side: list pending pagers, peek at one,
discard after Attending. Discard is the "I've Consolidated this — git
log carries the receipt" signal.
"""

from __future__ import annotations

import typer

from sweep import observe, retro_state


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


@retro_app.command("record")
def retro_record(
    subjective: str = typer.Option(..., "--subjective", "-s",
                                    help="S — what the system said (events)"),
    objective: str = typer.Option(..., "--objective", "-o",
                                   help="O — what the counters/derivations show"),
    assessment: str = typer.Option(..., "--assessment", "-a",
                                    help="A — diagnosis, naming codebase components"),
    plan: str = typer.Option(..., "--plan", "-p",
                              help="P — concrete commits to make, or '(none)' for an empty-P round"),
    slug: str = typer.Option(None, "--slug",
                              help="round slug; default is YYYY-MM-DD-HHMM UTC"),
) -> None:
    """Record one SOAP round.

    Argparse enforces the SOAP shape (all four sections required). The
    substrate decides whether this round opens a new file or appends to
    the active empty-P chain. The observe cursor advances to current
    EOF on success, so the next record() reads only fresh events.

    Cap behavior: if a NEW file would push the directory past the cap,
    record refuses with exit code 1. Appending to an existing empty-P
    chain is always allowed (the backward pass must keep folding even
    under halt).
    """
    # Snapshot the events range for this round, then advance the cursor.
    events_from = observe.cursor_get()
    observe.events_since_cursor(advance=True)
    events_to = observe.cursor_get()

    block_slug = slug or retro_state.slug_for_now()
    round_block = retro_state.ROUND_TEMPLATE.format(
        slug=block_slug,
        events_from=events_from,
        events_to=events_to,
        subjective=subjective.strip(),
        objective=objective.strip(),
        assessment=assessment.strip(),
        plan=plan.strip(),
    )
    try:
        path = retro_state.record_round(round_block, slug=block_slug)
    except RuntimeError as e:
        # Cap reached. Rewind the cursor so the next attempt (after the
        # human clears a pager) sees the same events range.
        observe.cursor_set(events_from)
        raise typer.Exit(code=1) from e

    appended = (retro_state.most_recent_retro() is not None
                and path.name != f"{block_slug}.md")
    n = len(retro_state.list_retros())
    halted = " (PIPELINE HALTED)" if retro_state.is_halted() else ""
    mode = "appended to" if appended else "created"
    print(f"{mode} {path.name}  events {events_from}..{events_to}  "
          f"retros {n}/{retro_state.RETRO_CAP}{halted}")
