"""`sweep hygraph` — compact view of the pipeline hypothesis graph.

Source: `HYPOTHESIS_GRAPH.md` at the repo root. Shows:
  • Unresolved hypotheses — no `**Status:**` line, or status starts with
    PRE-REGISTERED (treatment launched, no outcomes yet).
  • Recently resolved hypotheses — top N by parsed date from the status
    line. Status lines often carry e.g. `(2026-05-16, retro this-session)`
    or `(N=3, 2026-05-14)`; we grep YYYY-MM-DD from the line.

Markdown output, formatted to match the wasteboard / inbox / lanes
views so it slots cleanly into the TUI rotation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import typer


GRAPH_PATH = Path(__file__).resolve().parent.parent.parent / "HYPOTHESIS_GRAPH.md"
TOP_N_RESOLVED = 10

_HEADER_RE = re.compile(r"^## (H[0-9]+[a-z]?): (.+?)\s*$")
_STATUS_RE = re.compile(r"^\*\*Status:\s*(.+?)\s*$", re.IGNORECASE)
_DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")


@dataclass
class Hypothesis:
    id: str            # "H0", "H2a", ...
    title: str
    status_text: str   # the full status line minus "**Status:**" prefix; "" if no line
    date: str          # YYYY-MM-DD parsed from status_text, or "" if none

    @property
    def is_resolved(self) -> bool:
        if not self.status_text:
            return False
        head = self.status_text.split(".")[0].strip().upper()
        # PRE-REGISTERED = treatment running, no outcomes yet → unresolved.
        return not head.startswith("PRE-REGISTERED")


def parse_graph(text: str) -> list[Hypothesis]:
    """Split on `## H<N>:` headers, capture first **Status:** line per section."""
    out: list[Hypothesis] = []
    cur_id: str | None = None
    cur_title: str = ""
    cur_status: str = ""
    for line in text.splitlines():
        m = _HEADER_RE.match(line)
        if m:
            if cur_id is not None:
                date_m = _DATE_RE.search(cur_status)
                out.append(Hypothesis(
                    id=cur_id, title=cur_title,
                    status_text=cur_status,
                    date=date_m.group(1) if date_m else "",
                ))
            cur_id = m.group(1)
            cur_title = m.group(2)
            cur_status = ""
            continue
        if cur_id is not None and not cur_status:
            sm = _STATUS_RE.match(line)
            if sm:
                cur_status = sm.group(1)
    if cur_id is not None:
        date_m = _DATE_RE.search(cur_status)
        out.append(Hypothesis(
            id=cur_id, title=cur_title,
            status_text=cur_status,
            date=date_m.group(1) if date_m else "",
        ))
    return out


def _status_chip(text: str) -> str:
    """Trim the status to a short chip — first clause, before any '('."""
    if not text:
        return "—"
    chip = text.split(".")[0].strip().rstrip("*").rstrip()
    # Drop trailing parenthetical so "CONFIRMED (N=1, 2026-05-14)" → "CONFIRMED".
    paren = chip.find("(")
    if paren > 0:
        chip = chip[:paren].strip()
    return chip[:30]


def _render(hyps: list[Hypothesis]) -> str:
    unresolved = [h for h in hyps if not h.is_resolved]
    resolved = [h for h in hyps if h.is_resolved]
    # Sort resolved by date desc; undated go to the end in graph order.
    resolved.sort(key=lambda h: (h.date or ""), reverse=True)
    recent = resolved[:TOP_N_RESOLVED]

    lines: list[str] = ["# Hypothesis graph", ""]

    if unresolved:
        lines += [f"## Unresolved ({len(unresolved)})", "", "```"]
        idw = max(len(h.id) for h in unresolved)
        for h in unresolved:
            chip = _status_chip(h.status_text)
            lines.append(f"{h.id.ljust(idw)}  {chip.ljust(16)}  {h.title}")
        lines += ["```", ""]
    else:
        lines += ["## Unresolved (0)", "", "_All hypotheses have a status._", ""]

    if recent:
        lines += [f"## Recently resolved (top {len(recent)})", "", "```"]
        idw = max(len(h.id) for h in recent)
        for h in recent:
            chip = _status_chip(h.status_text)
            date = h.date or "—"
            lines.append(f"{h.id.ljust(idw)}  {date}  {chip.ljust(20)}  {h.title}")
        lines += ["```", ""]

    return "\n".join(lines)


def register(app: typer.Typer) -> None:
    @app.command("hygraph")
    def hygraph() -> None:
        """Show unresolved + recently-resolved hypotheses from
        HYPOTHESIS_GRAPH.md."""
        if not GRAPH_PATH.exists():
            typer.echo(f"# Hypothesis graph\n\n_{GRAPH_PATH} not found._")
            return
        try:
            text = GRAPH_PATH.read_text()
        except OSError as e:
            typer.echo(f"# Hypothesis graph\n\n_Read failed: {e}_")
            return
        hyps = parse_graph(text)
        typer.echo(_render(hyps))
