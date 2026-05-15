"""Operator flags — pipeline-wide dry mode and soft-pause.

Two flag files at ~/.sweep/control/, presence-only (the file IS the
state, content is ignored). Same pattern as retro_state — atomic writes
via io_safe, no parsing. Three surfaces (CLI subcommands, TUI key binds,
direct fs manipulation) are interchangeable because they all bottom out
on the same files.

- dry: actors run the full forward pass but skip external mutations.
  In-memory work, tests, attestations, observability all still fire;
  only writes that hit the outside world (inbox delivery, gh pr create,
  git push) are gated. The line rehearses without touching the world.
- paused: forward-pass actors no-op at takt entry; in-flight work
  completes normally. Operator-initiated and clears manually, distinct
  from the retro-cap halt which is automatic backpressure.
"""

from __future__ import annotations

from pathlib import Path

from sweep.io_safe import atomic_write_text


CONTROL = Path.home() / ".sweep" / "control"
DRY_FLAG = CONTROL / "dry"
PAUSED_FLAG = CONTROL / "paused"


def is_dry() -> bool:
    """True iff ~/.sweep/control/dry exists."""
    return DRY_FLAG.exists()


def is_paused() -> bool:
    """True iff ~/.sweep/control/paused exists."""
    return PAUSED_FLAG.exists()


def set_dry(v: bool) -> None:
    """Toggle the dry flag. Idempotent on both directions."""
    _set(DRY_FLAG, v)


def set_paused(v: bool) -> None:
    """Toggle the soft-pause flag. Idempotent on both directions."""
    _set(PAUSED_FLAG, v)


def _set(path: Path, v: bool) -> None:
    if v:
        atomic_write_text(path, "")
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass
