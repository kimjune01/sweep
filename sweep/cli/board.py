"""`sweep board` — kanban swim lanes, no metrics. Just PRs by station."""

from __future__ import annotations

import typer

from sweep.inbox_state import inbox_states


STATIONS = ["drip", "investigate", "qa", "retro"]


def register(app: typer.Typer) -> None:
    app.command("board")(board)


def board(
    include_retro: bool = typer.Option(False, "--retro", help="Include the retro/wait column"),
) -> None:
    """Column view: which PR is in which station. No numerics."""
    cols = [s for s in STATIONS if include_retro or s != "retro"]

    items: dict[str, list[str]] = {}
    for actor in cols:
        s = inbox_states(actor)
        msgs = sorted(s["queued"] + s["in_flight"], key=lambda x: x.get("ts", ""))
        items[actor] = [
            (
                f"[{m.get('repo', '?')}#{m.get('pr', '-')}]"
                f"(https://github.com/{m.get('repo', '')}/pull/{m.get('pr', '')})"
            )
            for m in msgs
        ]

    height = max((len(items[a]) for a in cols), default=0)
    headers = [f"{a} ({len(items[a])})" for a in cols]

    print("| " + " | ".join(headers) + " |")
    print("|" + "|".join("---" for _ in cols) + "|")
    if height == 0:
        print("| " + " | ".join("_empty_" for _ in cols) + " |")
        return
    for row in range(height):
        cells = []
        for actor in cols:
            col = items[actor]
            cells.append(col[row] if row < len(col) else " ")
        print("| " + " | ".join(cells) + " |")
