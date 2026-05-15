"""Append-only log of `sweep` invocations that failed because the
subcommand or option didn't exist.

The skill markdown calls `sweep <verb>` shapes that may not be built yet.
Each failed call is the strongest possible evidence the shape should
exist — an agent already named the verb-noun by reaching for it. Retro
reads this log to prioritize CLI work.

State file: `~/.sweep/missing-calls.jsonl`, one JSON object per call,
append-only. Latest-line-wins isn't a thing here — every reach is its
own datum.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

from sweep.io_safe import atomic_write_text

LOG = Path.home() / ".sweep" / "missing-calls.jsonl"


def record(argv: list[str], reason: str) -> None:
    """Append one *implicit* missing-call event — an agent reached for a
    CLI shape that doesn't exist, the harness caught the failure, and
    this records the reach. argv is sys.argv[1:] of the failed
    invocation; reason is a short string from the Typer/click exception."""
    LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "kind": "reach",  # implicit — agent tried and failed
        "argv": argv,
        "reason": reason,
        "cwd": os.getcwd(),
    }
    line = json.dumps(entry, separators=(",", ":")) + "\n"
    with LOG.open("a") as f:
        f.write(line)


def wish(argv: list[str], reason: str) -> dict:
    """Append one *explicit* wish — an agent (or human) deliberately
    files a request for a CLI shape that should exist, with a stated
    reason. Higher-signal than `record` because the reason is articulated
    instead of inferred from a syntactic guess. Returns the entry."""
    LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "kind": "wish",  # explicit — deliberate request with a reason
        "argv": argv,
        "reason": reason,
        "cwd": os.getcwd(),
    }
    line = json.dumps(entry, separators=(",", ":")) + "\n"
    with LOG.open("a") as f:
        f.write(line)
    return entry


def read_all() -> list[dict]:
    if not LOG.exists():
        return []
    out: list[dict] = []
    for raw in LOG.read_text().splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            continue  # tolerate hand-edits
    return out


def wishlist(since: dt.datetime | None = None) -> list[dict]:
    """Return calls grouped by (argv tuple) with vote count + latest ts,
    sorted by votes desc. Each entry:
      {argv, reach_count, wish_count, votes, last_ts, reasons}.

    Votes: implicit reaches count 1, explicit wishes count 3 — a
    deliberate request with a reason is stronger signal than a syntactic
    guess. The weighting is policy that may shift with use; keep it in
    one place."""
    by_call: dict[tuple, dict] = {}
    for e in read_all():
        if since:
            try:
                ts = dt.datetime.fromisoformat(e["ts"])
            except (KeyError, ValueError):
                continue
            if ts < since:
                continue
        key = tuple(e.get("argv", []))
        slot = by_call.setdefault(
            key,
            {
                "argv": list(key),
                "reach_count": 0,
                "wish_count": 0,
                "votes": 0,
                "last_ts": "",
                "reasons": set(),
            },
        )
        kind = e.get("kind", "reach")
        if kind == "wish":
            slot["wish_count"] += 1
            slot["votes"] += 3
        else:
            slot["reach_count"] += 1
            slot["votes"] += 1
        if e.get("ts", "") > slot["last_ts"]:
            slot["last_ts"] = e["ts"]
        if e.get("reason"):
            slot["reasons"].add(e["reason"])
    out = []
    for v in by_call.values():
        v["reasons"] = sorted(v["reasons"])
        out.append(v)
    out.sort(key=lambda x: (-x["votes"], x["last_ts"]))
    return out


def clear() -> None:
    """Erase the log. Used after a CLI surface lands so the wishlist
    reflects current gaps, not historical ones already filled."""
    if LOG.exists():
        atomic_write_text(LOG, "")
