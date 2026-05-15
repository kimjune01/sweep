"""`sweep missing` — print the CLI wishlist.

Every `sweep` invocation that fails with an unknown subcommand / option
gets appended to `~/.sweep/missing-calls.jsonl`. This command reads that
log and groups by call shape, ranked by frequency.

The wishlist is the strongest evidence for what to build next: agents
demonstrated the need by reaching for it.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Optional

import typer

from sweep import missing_calls


def register(app: typer.Typer) -> None:
    app.command("missing")(missing)


def missing(
    since: Optional[str] = typer.Option(
        None, "--since", help="ISO date (YYYY-MM-DD) — only include calls after this"
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON (default: human)"),
    clear_after: bool = typer.Option(
        False, "--clear", help="After printing, truncate the log (use once a wishlist entry is built)"
    ),
) -> None:
    """Show CLI commands agents tried to call that didn't exist."""
    cutoff: Optional[dt.datetime] = None
    if since:
        try:
            cutoff = dt.datetime.fromisoformat(since).replace(tzinfo=dt.timezone.utc)
        except ValueError as e:
            raise typer.BadParameter(f"--since must be ISO date: {e}")
    rows = missing_calls.wishlist(since=cutoff)
    if json_out:
        print(json.dumps(rows, indent=2))
    else:
        if not rows:
            print("# wishlist empty — no missing calls or wishes recorded")
        else:
            print(f"# {len(rows)} distinct missing calls (votes = reaches + 3·wishes)")
            for r in rows:
                argv_str = " ".join(r["argv"])
                tag = ""
                if r["wish_count"]:
                    tag = f" (W:{r['wish_count']} R:{r['reach_count']})"
                elif r["reach_count"]:
                    tag = f" (R:{r['reach_count']})"
                print(f"  [{r['votes']:3d} votes]{tag} sweep {argv_str}")
                if r["reasons"]:
                    for rsn in r["reasons"]:
                        print(f"           reason: {rsn}")
    if clear_after:
        missing_calls.clear()
        print("# cleared", file=__import__("sys").stderr)
