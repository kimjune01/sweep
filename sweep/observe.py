"""Observe — append-only events + SQLite counters for retro.

Two surfaces, deliberately thin:

  event(kind, **payload)  → one line on ~/.sweep/events.jsonl
  incr(key, n=1)          → bump ~/.sweep/counters.db

Counters answer "how often" without folding the event log. Events answer
"what happened" when retro needs the body. Some mutations call both —
counters are pre-aggregated derivatives, events are the source.

No schemas. Kinds and keys are conventional strings; retro discovers
them by reading what landed. The forward pass writes freely; the
backward pass compresses.

Read helpers:
  counter(key)              → int (0 if unseen)
  counters_with_prefix(p)   → dict[key, value]
  counters_all()            → dict[key, value]
  events_recent(limit, kind?) → list[dict] (newest first)

All writes are best-effort: a logging primitive that throws on every
call would corrupt the pipeline it's supposed to observe. Swallow
exceptions and keep moving.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path

from sweep.io_safe import atomic_write_text


EVENTS = Path.home() / ".sweep" / "events.jsonl"
COUNTERS_DB = Path.home() / ".sweep" / "counters.db"
ARCHIVE_CURSOR = Path.home() / ".sweep" / "events.cursor"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS counters (
    key            TEXT PRIMARY KEY,
    value          INTEGER NOT NULL,
    first_seen_ts  TEXT NOT NULL,
    last_inc_ts    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_counters_last ON counters(last_inc_ts);
"""


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _conn() -> sqlite3.Connection:
    # timeout=5: under concurrent writers (worker + CLI + scripts), SQLite's
    # deferred isolation lets two writers both observe "no row" before either
    # commits, so the loser hits SQLITE_BUSY. Wait up to 5s for the writer
    # lock before raising; with the upsert pattern below, that's enough for
    # all realistic contention. Without this, the loser's incr is silently
    # dropped by the bare-except in incr().
    COUNTERS_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(COUNTERS_DB), timeout=5)
    conn.executescript(_SCHEMA)
    return conn


# ---------------------------------------------------------------- writers


def event(kind: str, **payload) -> None:
    """Append one line to events.jsonl. Never raises."""
    try:
        EVENTS.parent.mkdir(parents=True, exist_ok=True)
        record = {"ts": _now(), "kind": kind, **payload}
        with open(EVENTS, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except Exception:
        pass


def incr(key: str, n: int = 1) -> None:
    """UPSERT a counter by `n`. Never raises."""
    if n == 0:
        return
    try:
        ts = _now()
        with _conn() as conn:
            conn.execute(
                """INSERT INTO counters (key, value, first_seen_ts, last_inc_ts)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET
                       value = value + excluded.value,
                       last_inc_ts = excluded.last_inc_ts""",
                (key, n, ts, ts),
            )
            conn.commit()
    except Exception:
        pass


# ---------------------------------------------------------------- readers


def counter(key: str) -> int:
    try:
        with _conn() as conn:
            row = conn.execute(
                "SELECT value FROM counters WHERE key = ?", (key,)
            ).fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0


def counters_with_prefix(prefix: str) -> dict[str, int]:
    try:
        with _conn() as conn:
            rows = conn.execute(
                "SELECT key, value FROM counters WHERE key LIKE ? ORDER BY key",
                (prefix + "%",),
            ).fetchall()
        return {k: int(v) for k, v in rows}
    except Exception:
        return {}


def counters_all() -> dict[str, int]:
    try:
        with _conn() as conn:
            rows = conn.execute(
                "SELECT key, value FROM counters ORDER BY key"
            ).fetchall()
        return {k: int(v) for k, v in rows}
    except Exception:
        return {}


def events_recent(limit: int = 50, kind: str | None = None) -> list[dict]:
    """Tail of events.jsonl, newest first. O(file size) — fine for retro,
    not for hot paths."""
    if not EVENTS.exists():
        return []
    try:
        lines = EVENTS.read_text().splitlines()
    except OSError:
        return []
    out: list[dict] = []
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if kind and r.get("kind") != kind:
            continue
        out.append(r)
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------- cursor
#
# The cursor demarcates "retro (or an archiver) has consumed events up to
# this byte offset." Lines >= offset are unread; lines < offset are safe to
# cold-archive when the pipeline trusts retro enough to flush. For now we
# don't flush — events.jsonl stays durable. The cursor just gives readers
# a watermark so they can process incrementally without re-walking history.
#
# Stored as {"offset": int, "ts": iso8601} so the timestamp is human-readable
# during the period where we're still learning the pipeline's shape.


def cursor_get() -> int:
    """Return the byte offset of the last consumed event. 0 if unset."""
    if not ARCHIVE_CURSOR.exists():
        return 0
    try:
        return int(json.loads(ARCHIVE_CURSOR.read_text()).get("offset", 0))
    except (json.JSONDecodeError, OSError, ValueError):
        return 0


def cursor_set(offset: int) -> None:
    """Mark events up to `offset` bytes as consumed. Caller advances after
    successfully processing the range; never auto-advanced by writers.

    Atomic via write-then-rename so a crash mid-write can't rewind the
    cursor to 0 — cursor_get falls back to 0 on JSONDecodeError, which
    would force retro to re-walk the entire event log if a torn write
    were visible."""
    try:
        atomic_write_text(
            ARCHIVE_CURSOR,
            json.dumps({"offset": int(offset), "ts": _now()}),
        )
    except OSError:
        pass


def events_since_cursor(*, advance: bool = False) -> list[dict]:
    """Read events after the cursor. If `advance=True`, move the cursor to
    end-of-file once the read succeeds. The advance is intentionally opt-in:
    retro shouldn't move the watermark until it has folded the events into
    durable artifacts."""
    if not EVENTS.exists():
        return []
    start = cursor_get()
    try:
        with open(EVENTS, "rb") as f:
            f.seek(start)
            payload = f.read()
            end = f.tell()
    except OSError:
        # Disk full / file removed / permission flipped — return empty
        # rather than letting the caller (CLI or retro) crash.
        return []
    out: list[dict] = []
    try:
        decoded = payload.decode("utf-8", errors="replace")
    except UnicodeDecodeError:
        decoded = ""
    for line in decoded.splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if advance:
        cursor_set(end)
    return out
