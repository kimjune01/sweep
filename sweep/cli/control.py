"""`sweep dry …` and `sweep pause …` — operator toggles for the two
pipeline-wide control flags.

Mirrors the shape of `sweep retro …`: tiny, file-backed, three verbs
(on / off / status). Same files the TUI writes, so all surfaces are
interchangeable.
"""

from __future__ import annotations

import typer

from sweep import control_state


dry_app = typer.Typer(help="Dry mode — skip external mutations", no_args_is_help=True)
pause_app = typer.Typer(help="Soft-pause — forward-pass actors no-op at takt entry",
                        no_args_is_help=True)


@dry_app.command("on")
def dry_on() -> None:
    """Enable dry mode. Actors run; external mutations are skipped."""
    control_state.set_dry(True)
    print("dry: on")


@dry_app.command("off")
def dry_off() -> None:
    """Disable dry mode."""
    control_state.set_dry(False)
    print("dry: off")


@dry_app.command("status")
def dry_status() -> None:
    """One-line state."""
    print(f"dry: {'on' if control_state.is_dry() else 'off'}")


@pause_app.command("on")
def pause_on() -> None:
    """Enable soft-pause. In-flight work completes; no new dequeues."""
    control_state.set_paused(True)
    print("paused: on")


@pause_app.command("off")
def pause_off() -> None:
    """Clear soft-pause. Forward-pass actors resume at their next takt."""
    control_state.set_paused(False)
    print("paused: off")


@pause_app.command("status")
def pause_status() -> None:
    """One-line state."""
    print(f"paused: {'on' if control_state.is_paused() else 'off'}")
