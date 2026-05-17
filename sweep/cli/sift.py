"""`sweep sift …` — legacy star-cursor sweep escape hatch.

The live pipeline is scout (search) → sift (per-issue screen). This
CLI fires the legacy `prospect_one_pass` star-cursor activity directly,
useful for one-off backfills and debugging. The actor and the routine
runbook do not use it."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from pathlib import Path

import typer

from sweep.activities.sift import (
    CURSOR_FILE,
    ProspectRunRequest,
    prospect_one_pass,
)


sift_app = typer.Typer(help="Sift — sweep GitHub for actionable issues (legacy star-cursor pass)", no_args_is_help=True)


@sift_app.command("run")
def sift_run(
    budget: int = typer.Option(20, help="Max repos to scan this pass"),
    issue_limit: int = typer.Option(5, help="Max issues to surface per repo"),
    language: list[str] = typer.Option([], help="Filter by language (repeatable)"),
    floor: int = typer.Option(100, help="Star floor — below this, lap resets"),
) -> None:
    """One pass: descend the star cursor, deposit actionable issues into triaged.jsonl."""
    req = ProspectRunRequest(
        budget=budget,
        issue_limit_per_repo=issue_limit,
        languages=list(language),
        floor=floor,
    )
    result = asyncio.run(prospect_one_pass(req))
    print(json.dumps(asdict(result), indent=2))


@sift_app.command("cursor")
def sift_cursor() -> None:
    """Show the current sift cursor state."""
    if not CURSOR_FILE.exists():
        print("# cursor not initialized — first run will start at the top")
        return
    print(CURSOR_FILE.read_text())


@sift_app.command("reset")
def sift_reset() -> None:
    """Reset the cursor to the top (start a fresh lap)."""
    if CURSOR_FILE.exists():
        CURSOR_FILE.unlink()
        print("# cursor reset — next pass starts at the top of the star ladder")
    else:
        print("# cursor was already absent")
