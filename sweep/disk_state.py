"""Disk-usage state: same shape as org_state.

Worker writes (`refresh_if_stale` from sift tick), display reads
(`cli/waste.py`). Reads never spawn `du`. If the worker stops
running, the disk-pressure section disappears from displays — that
absence is the andon signal, not a stale-but-displayed number.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from sweep.io_safe import atomic_write_text


STATE = Path.home() / ".sweep" / "state" / "disk.json"
# 5 minutes — disk usage moves slowly enough that staleness is fine,
# but quickly enough that a heavy worktree-create-then-discard cycle
# updates within an operator's cockpit-glance window.
BG_REFRESH_TTL = 5 * 60.0
# Worktrees is the single tracked path today. Add more paths here if
# we ever want per-subsystem breakdowns.
PATHS = [Path.home() / ".sweep" / "worktrees"]


def _du_bytes(path: Path) -> int | None:
    """`du -sk` — O(stat-cached), faster than rglob. Called only
    from the background refresher, never from display surfaces."""
    if not path.exists():
        return 0
    try:
        out = subprocess.run(
            ["du", "-sk", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        if out.returncode != 0:
            return None
        return int(out.stdout.split()[0]) * 1024
    except (subprocess.TimeoutExpired, ValueError, IndexError):
        return None


def _load() -> dict:
    if not STATE.exists():
        return {}
    try:
        return json.loads(STATE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def refresh_all() -> dict:
    """Re-stat each tracked path and write to disk.json atomically."""
    now = time.time()
    out: dict = {}
    for p in PATHS:
        b = _du_bytes(p)
        if b is not None:
            out[str(p)] = {"bytes": b, "ts": now}
    STATE.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(STATE, json.dumps(out))
    return out


def refresh_if_stale() -> bool:
    """No-op if the stamp is younger than BG_REFRESH_TTL; otherwise
    refreshes. Returns True if a refresh ran. Called from the sift
    tick."""
    data = _load()
    oldest = min((e.get("ts", 0.0) for e in data.values()), default=0.0)
    if data and time.time() - oldest < BG_REFRESH_TTL:
        return False
    refresh_all()
    return True
