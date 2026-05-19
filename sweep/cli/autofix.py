"""`sweep autofix` — install missing toolchain deps into sweep-tester.

CLI surface around the autofix activities. Two usage shapes:

  sweep autofix install <tool>       — install a known tool by name
  sweep autofix run "<failure text>" — pattern-match + install allowlisted

`detect` is a dry run: prints what `run` would install without acting.

Workflows that hit missing-tool failures can call the same activities
(`autofix_install`, `autofix_from_text`) directly from their except
handler — no cross-actor signaling, no card ceremony, the activity
runs inline and returns to the calling actor.
"""

from __future__ import annotations

import asyncio

import typer
from rich.console import Console
from rich.table import Table

from sweep.activities.autofix import (
    ALLOWLIST,
    autofix_from_text,
    autofix_install,
    detect_missing_tools,
)


autofix_app = typer.Typer(
    help="Install missing toolchain deps into sweep-tester.",
    invoke_without_command=False,
)
console = Console()


@autofix_app.command("install")
def cli_install(
    tool: str = typer.Argument(..., help="Tool name (e.g. ruff, mold, jq)."),
) -> None:
    """Install one allowlisted tool. Edits the Dockerfile and dispatches
    a rebuild in the background. Idempotent."""
    if tool not in ALLOWLIST:
        console.print(f"[red]{tool!r} not in allowlist[/red]")
        raise typer.Exit(code=1)
    r = asyncio.run(autofix_install(tool))
    console.print(r)
    if not r.get("handled"):
        raise typer.Exit(code=1)


@autofix_app.command("run")
def cli_run(
    text: str = typer.Argument(..., help="Failure message to scan + autofix."),
) -> None:
    """Pattern-match `text` and install every allowlisted tool detected.
    Dispatches a single rebuild if anything was edited."""
    r = asyncio.run(autofix_from_text(text))
    console.print(r)
    if not r.get("handled"):
        raise typer.Exit(code=1)


@autofix_app.command("detect")
def cli_detect(
    text: str = typer.Argument(..., help="Failure message to scan."),
) -> None:
    """Dry run — print every missing-tool name extracted and whether
    it's allowlisted. No side effects."""
    tools = detect_missing_tools(text)
    if not tools:
        console.print("[yellow]no missing-tool pattern matched[/yellow]")
        return
    t = Table()
    t.add_column("tool")
    t.add_column("allowlisted")
    t.add_column("install")
    for tool in tools:
        if tool in ALLOWLIST:
            method, pkg = ALLOWLIST[tool]
            t.add_row(tool, "[green]yes[/green]", f"{method}:{pkg}")
        else:
            t.add_row(tool, "[red]no[/red]", "")
    console.print(t)
