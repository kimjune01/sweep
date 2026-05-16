"""`sweep lanes` — swim lanes, no metrics. Just PRs by station."""

from __future__ import annotations

import typer

from sweep.inbox_state import inbox_states


# Pipeline order, left → right:
#   triaged     — LLM (/triage output): issues scored, awaiting investigation
#   investigate — LLM (/investigate): root-cause + fix branch
#   qa          — LLM, runs gates
#   drip        — LLM, paces pushes
#   in review   — reviewer holds the ball (retro/wait inbox)
#   respondable — ball back to you (human) after reviewer engages
STATIONS = [
    ("triaged",     "triaged"),
    ("investigate", "investigate"),
    ("qa",          "qa"),
    ("drip",        "drip"),
    ("retro",       "in review"),
    ("respondable", "respondable"),
]


def register(app: typer.Typer) -> None:
    app.command("lanes")(lanes)


def render_lanes(height: int = 7) -> list[str]:
    """Build the swim-lane lines without printing — shared with
    `sweep cockpit` so the conveyor section uses the same rendering as the
    standalone `sweep lanes` command. Returns the full markdown block."""
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

    lines: list[str] = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join("---" for _ in cols) + "|")
    if max_rows == 0:
        lines.append("| " + " | ".join("_empty_" for _ in cols) + " |")
        return lines
    for row in range(max_rows):
        cells = []
        for actor, _label in cols:
            col = display[actor]
            cells.append(col[row] if row < len(col) else " ")
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def lanes(
    height: int = typer.Option(7, "--height", help="Max rows per column before truncating"),
    as_json: bool = typer.Option(False, "--json", help="Emit structured data for the TUI overlay"),
) -> None:
    """Column view: which PR is in which station. No numerics, truncates tall columns.

    With ``--json``, emits a list of columns ``[{label, items: [{repo, pr, in_flight}]}]``
    for the lanes TUI overlay to consume (`sweep tui` → `l`).
    """
    if as_json:
        import json as _json
        cols = []
        for actor, label in STATIONS:
            s = inbox_states(actor)
            in_flight_ids = {m.get("msg_id") for m in s["in_flight"]}
            msgs = sorted(s["queued"] + s["in_flight"], key=lambda x: x.get("ts", ""))
            items = [{
                "repo": m.get("repo", "?"),
                "pr": m.get("pr") or "-",
                "in_flight": m.get("msg_id") in in_flight_ids,
            } for m in msgs]
            cols.append({"label": label, "items": items})
        print(_json.dumps(cols))
        return
    print("# sweep lanes — PRs by station")
    print()
    for line in render_lanes(height):
        print(line)
