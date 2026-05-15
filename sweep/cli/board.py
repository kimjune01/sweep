"""`sweep board` — kanban swim lanes, no metrics. Just PRs by station."""

from __future__ import annotations

import typer

from sweep.inbox_state import inbox_states


# station → display label. retro is "in review" — PRs awaiting maintainer
# attention with no action signal from us.
STATIONS = [
    ("investigate", "investigate"),
    ("qa",          "qa"),
    ("drip",        "drip"),
    ("retro",       "in review"),
]


def register(app: typer.Typer) -> None:
    app.command("board")(board)


def board(
    height: int = typer.Option(7, "--height", help="Max rows per column before truncating"),
) -> None:
    """Column view: which PR is in which station. No numerics, truncates tall columns."""
    cols = STATIONS

    items: dict[str, list[str]] = {}
    counts: dict[str, int] = {}
    for actor, _label in cols:
        s = inbox_states(actor)
        in_flight_ids = {m.get("msg_id") for m in s["in_flight"]}
        msgs = sorted(s["queued"] + s["in_flight"], key=lambda x: x.get("ts", ""))
        counts[actor] = len(msgs)
        rendered: list[str] = []
        for m in msgs:
            link = (
                f"[{m.get('repo', '?')}#{m.get('pr', '-')}]"
                f"(https://github.com/{m.get('repo', '')}/pull/{m.get('pr', '')})"
            )
            prefix = "✈️ " if m.get("msg_id") in in_flight_ids else ""
            rendered.append(f"{prefix}{link}")
        items[actor] = rendered

    # Truncate each column to `height` rows. Reserve the last row for the
    # truncation indicator when a column has more.
    display: dict[str, list[str]] = {}
    for actor, _label in cols:
        col = items[actor]
        if len(col) <= height:
            display[actor] = col
        else:
            shown = col[: max(0, height - 1)]
            shown.append(f"_… +{len(col) - len(shown)} more_")
            display[actor] = shown

    max_rows = max((len(display[a]) for a, _ in cols), default=0)
    headers = [f"{label} ({counts[a]})" for a, label in cols]

    print("# sweep board — PRs by station")
    print()
    print("| " + " | ".join(headers) + " |")
    print("|" + "|".join("---" for _ in cols) + "|")
    if max_rows == 0:
        print("| " + " | ".join("_empty_" for _ in cols) + " |")
        return
    for row in range(max_rows):
        cells = []
        for actor, _label in cols:
            col = display[actor]
            cells.append(col[row] if row < len(col) else " ")
        print("| " + " | ".join(cells) + " |")
