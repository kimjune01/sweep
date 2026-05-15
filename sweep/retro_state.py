"""Retro pager directory — SOAP one-pagers, capped at 2.

The backward pass writes a SOAP one-pager per cycle to ~/.sweep/retros/.
Each file is human-attended: read it, decide what to act on, commit any
code changes referencing the retro's slug, then delete the file. Deletion
is the "I've Attended to this" signal — the pipeline reads the file count
as backpressure.

Cap = 2. The third concurrent file is the halt signal: forward-pass
actors check is_halted() at their takt boundary and early-return until
the human clears at least one file. Git history is the persistent record
of what was acted on; the retro file itself is ephemeral staging.

The skill that writes these files lives in ~/.claude/skills/retro/skill.md
and uses observe.events_since_cursor + observe.counters_with_prefix to
fold the cycle's data into prose. This module is the substrate the skill
writes through.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

from sweep.io_safe import atomic_write_text


RETROS = Path.home() / ".sweep" / "retros"
RETRO_CAP = 2


# The SOAP one-pager contract. Documented here so the /retro skill and any
# human reader share the same template. The skill renders this shape; the
# A section names codebase components (qa cascade, prospect labels, gh_io
# cache, observe) — projection through the Natural Framework is unnecessary
# because the pipeline is already structurally decomposed by role.
SOAP_TEMPLATE = """\
# Retro {slug} — events {events_from}..{events_to}

## S
{subjective}

## O
{objective}

## A
{assessment}

## P
{plan}
"""


@dataclass(frozen=True)
class RetroFile:
    name: str       # filename without extension, used as the slug
    path: Path
    written_at: dt.datetime


def _retros() -> list[RetroFile]:
    if not RETROS.exists():
        return []
    out: list[RetroFile] = []
    for p in sorted(RETROS.glob("*.md")):
        try:
            mtime = dt.datetime.fromtimestamp(p.stat().st_mtime, dt.timezone.utc)
        except OSError:
            continue
        out.append(RetroFile(name=p.stem, path=p, written_at=mtime))
    return out


def list_retros() -> list[RetroFile]:
    """Every pending retro, oldest first by filename (timestamps sort)."""
    return _retros()


def is_halted() -> bool:
    """True when the pager directory holds the cap. Forward-pass actors
    early-return until at least one file is cleared."""
    return len(_retros()) >= RETRO_CAP


def slug_for_now() -> str:
    """Conventional filename body: YYYY-MM-DD-HHMM."""
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d-%H%M")


def write_retro(content: str, *, slug: str | None = None) -> Path:
    """Lay down a retro file. Raises RuntimeError if the cap is full.

    Caller (the /retro skill) is responsible for the content shape — this
    function only enforces the cap and the atomic write. The slug defaults
    to the current minute; pass an explicit slug to override (e.g. when
    re-writing a draft).
    """
    if is_halted():
        raise RuntimeError(
            f"retro cap reached ({RETRO_CAP}); clear one of "
            f"{[r.name for r in _retros()]} before writing"
        )
    name = slug or slug_for_now()
    RETROS.mkdir(parents=True, exist_ok=True)
    path = RETROS / f"{name}.md"
    atomic_write_text(path, content if content.endswith("\n") else content + "\n")
    if is_halted():
        # Local import: observe.event swallows exceptions so this is best-
        # effort. Emitted exactly when the write brings the directory to
        # the cap, so retro readers see a clean "halt fired here" marker.
        from sweep import observe
        observe.event("pipeline_halted", retro=name, cap=RETRO_CAP)
    return path


def discard_retro(name: str) -> bool:
    """Delete one retro file by slug. Returns True if removed, False if
    the file didn't exist. Deletion is the human's 'Attended' signal."""
    path = RETROS / f"{name}.md"
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False
