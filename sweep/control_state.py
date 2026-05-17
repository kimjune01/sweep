"""Operator flags — pipeline-wide dry mode and soft-pause.

Two flag files at ~/.sweep/control/, presence-only (the file IS the
state, content is ignored). Same pattern as retro_state — atomic writes
via io_safe, no parsing. Three surfaces (CLI subcommands, TUI key binds,
direct fs manipulation) are interchangeable because they all bottom out
on the same files.

- dry: "no new public commitments / no new work." Narrowly scoped —
  only submit-actor honors it (at pause_gate.should_idle, the inbox-pull
  boundary). Other actors (respond, qa, investigate, etc.) keep
  flowing because once a PR is out there, the maintainer is on
  real-world time and we owe them a response regardless of operator
  pause/dry state. Cards pile in submit.jsonl while dry is on; `sweep
  dry off` drains. No special code paths — dry is just *time*.
- paused: forward-pass actors no-op at takt entry; in-flight work
  completes normally. Blanket gate (every actor's main loop calls
  pause_gate). Set by the operator (`sweep pause on`) or automatically
  by an andon firing (something broke → don't produce more). Clears
  when the operator runs `sweep pause off` OR when the last andon
  marker is cleared (operator signaling "ready to run").
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
