"""`sweep observe …` — read counters + events + cursor.

Forward pass writes via sweep.observe; this CLI is the backward window.
No writes here except cursor advance, which is a privileged operation
(retro will own it once the pipeline shape settles).
"""

from __future__ import annotations

import json

import typer

from sweep import observe


observe_app = typer.Typer(help="Counters + events for retro", no_args_is_help=True)


@observe_app.command("counters")
def observe_counters(
    prefix: str = typer.Option("", help="Only keys starting with this prefix"),
) -> None:
    """Print every counter (or those matching --prefix), sorted by key."""
    data = observe.counters_with_prefix(prefix) if prefix else observe.counters_all()
    if not data:
        print("# no counters recorded")
        return
    width = max(len(k) for k in data)
    for k, v in data.items():
        print(f"{k:<{width}}  {v}")


@observe_app.command("events")
def observe_events(
    limit: int = typer.Option(20, help="How many events (newest first)"),
    kind: str = typer.Option("", help="Filter to one event kind"),
) -> None:
    """Tail of events.jsonl, newest first."""
    rows = observe.events_recent(limit=limit, kind=kind or None)
    if not rows:
        print("# no events recorded")
        return
    for r in rows:
        print(json.dumps(r))


@observe_app.command("cursor")
def observe_cursor() -> None:
    """Show the consumed-events watermark + how many events are unread."""
    offset = observe.cursor_get()
    unread = len(observe.events_since_cursor(advance=False))
    print(f"offset:  {offset}")
    print(f"unread:  {unread}")


@observe_app.command("advance")
def observe_advance(
    yes: bool = typer.Option(False, "--yes", "-y", help="Confirm the advance"),
) -> None:
    """Move the cursor to end-of-file. Retro will own this; manual advance
    is for testing only — pass --yes to confirm."""
    if not yes:
        print("refusing to advance without --yes (retro should drive this)")
        raise typer.Exit(2)
    rows = observe.events_since_cursor(advance=True)
    print(f"advanced past {len(rows)} events; new offset = {observe.cursor_get()}")


@observe_app.command("event")
def observe_event(
    kind: str = typer.Argument(..., help="Event kind, e.g. triage_decision"),
    fields: list[str] = typer.Argument(None, help="key=value pairs; values parsed as JSON when possible"),
) -> None:
    """Append one structured event to events.jsonl. Skills (or any
    process) emit decisions this way so retro can join across stages.

    Example: sweep observe event triage_decision repo=foo/bar pr=12 \\
                 decision=drop reason=stale_label
    """
    payload: dict = {}
    for raw in fields or []:
        if "=" not in raw:
            raise typer.BadParameter(f"expected key=value, got {raw!r}")
        k, v = raw.split("=", 1)
        try:
            payload[k] = json.loads(v)
        except json.JSONDecodeError:
            payload[k] = v
    observe.event(kind, **payload)
    print(f"ok: {kind}")
