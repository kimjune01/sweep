"""`sweep lanes` — swim lanes, no metrics. Just PRs by station.

Point-in-time inventory: where each open PR currently sits across the
pipeline's stations. For flow accounting between stations (leaks,
screens, pending), see `sweep leakdog`.

Side effect: persists the displayed PR list, in glow's auto-numbering
order (row × col, top-to-bottom, left-to-right), to
~/.sweep/state/recent_lanes.json. `sweep pr <N>` resolves the integer
against this file so the operator can type `sweep pr 1` after a lanes
view to drill into the first listed PR.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from sweep.inbox_state import inbox_states, lane_assignments

RECENT_LANES_FILE = Path.home() / ".sweep" / "state" / "recent_lanes.json"


# Pipeline order, left → right:
#   triaged     — LLM (/triage output): issues scored, awaiting investigation
#   investigate — LLM (/investigate): root-cause + fix branch
#   qa          — LLM, runs gates
#   drip        — LLM, paces pushes
#   in flight   — reviewer holds the ball (wait-bucket audit, view-only)
#   human       — ball back to you after reviewer engages
STATIONS = [
    ("triaged",     "triaged"),
    ("investigate", "investigate"),
    ("qa",          "qa"),
    ("respond",     "respond"),
    ("retro_audit", "in flight"),
    ("human", "human"),
]


def register(app: typer.Typer) -> None:
    app.command("lanes")(lanes)


def render_lanes(height: int = 7) -> list[str]:
    """Build the swim-lane markdown lines without printing. Returns the
    full block including header and column-truncation indicators.

    Uses cross-actor `lane_assignments`: each (repo, pr) is assigned
    to exactly one station — its rightmost. Toyota-property kanban,
    not event-history per actor. The previous behavior double-counted
    a (repo, pr) into every actor inbox that had ever touched it."""
    cols = STATIONS

    # Single-pass partition. Returns {label: [msg, ...]}, each pair
    # appearing in exactly one column.
    columns_by_label = lane_assignments(cols)
    # For the ✈️ in_flight glyph we still need per-actor in_flight ids
    # (the assignment doesn't carry the queued vs in_flight distinction).
    in_flight_ids: set[str] = set()
    for actor, _label in cols:
        s = inbox_states(actor)
        in_flight_ids.update(m.get("msg_id") for m in s["in_flight"])

    items: dict[str, list[str]] = {}
    counts: dict[str, int] = {}
    for actor, label in cols:
        msgs = columns_by_label.get(label, [])
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

    # Persist render-order (repo, pr) for `sweep pr <N>` resolution.
    # Glow numbers reference-style links in source-text order, which
    # for a markdown table is row-by-row across columns. Only rows
    # that carry an actual link contribute an index; the truncation
    # row ("_… +N more_") has no URL so glow skips it. We build the
    # ordered list from `columns_by_label` sliced to the same depth
    # that `display` actually printed (height-1 when truncated).
    visible_per_col: dict[str, list[dict]] = {}
    for actor, label in cols:
        msgs = columns_by_label.get(label, [])
        if len(msgs) <= height:
            visible_per_col[actor] = msgs
        else:
            visible_per_col[actor] = msgs[: max(0, height - 1)]
    ordered: list[dict] = []
    for row in range(max_rows):
        for actor, _label in cols:
            msgs = visible_per_col[actor]
            if row < len(msgs):
                m = msgs[row]
                ordered.append({"repo": m.get("repo"), "pr": m.get("pr")})
    try:
        RECENT_LANES_FILE.parent.mkdir(parents=True, exist_ok=True)
        RECENT_LANES_FILE.write_text(json.dumps(ordered))
    except OSError:
        pass

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
        columns_by_label = lane_assignments(STATIONS)
        in_flight_ids: set[str] = set()
        for actor, _label in STATIONS:
            in_flight_ids.update(
                m.get("msg_id") for m in inbox_states(actor)["in_flight"]
            )
        cols = []
        for _actor, label in STATIONS:
            msgs = columns_by_label.get(label, [])
            items = [{
                "repo": m.get("repo", "?"),
                "pr": m.get("pr") or "-",
                "in_flight": m.get("msg_id") in in_flight_ids,
            } for m in msgs]
            cols.append({"label": label, "items": items})
        print(_json.dumps(cols))
        return
    print("# Sweep lanes")
    print()
    for line in render_lanes(height):
        print(line)
