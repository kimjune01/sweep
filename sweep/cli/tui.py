"""`sweep tui` — launch the operator bar.

Shells out to the Go binary at ``<repo>/bin/sweep-tui`` (or whatever's
on PATH, if you symlinked it). Makes the TUI structurally dependent on
the Python CLI being installed: you can only reach it through `sweep`,
so a missing-`sweep` failure mode is impossible.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import typer


def _binary_path() -> Path | None:
    """PATH first (matches the user's chosen install), then the
    in-repo binary as a fallback so a fresh clone works even before
    the `~/.local/bin` symlink is in place."""
    found = shutil.which("sweep-tui")
    if found:
        return Path(found)
    repo_binary = Path(__file__).resolve().parent.parent.parent / "bin" / "sweep-tui"
    if repo_binary.exists():
        return repo_binary
    return None


def register(app: typer.Typer) -> None:
    @app.command("tui")
    def tui() -> None:
        """Launch the operator action-bar TUI.

        On launch it runs `sweep up` (idempotent) and tears down only
        what it started on quit. One TUI per machine.
        """
        binary = _binary_path()
        if binary is None:
            typer.echo(
                "sweep-tui binary not found.\n"
                "Build it with: cd tui && go build -o ../bin/sweep-tui .",
                err=True,
            )
            raise typer.Exit(1)
        os.execv(str(binary), [str(binary)])
