"""Per-repo retro parameter file.

State: `~/.sweep/retro/<owner>-<repo>.jsonl`, append-only, one
`{ts, key, value, reason}` object per line. Last-value-wins per key on
read. Triage and drip consume the resolved param map.

This module is the only writer/reader the skills should use — the jsonl
shape stays in code, not in skill markdown.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

PARAMS_DIR = Path.home() / ".sweep" / "retro"


def _slug(repo: str) -> str:
    return repo.replace("/", "-")


def path_for(repo: str) -> Path:
    return PARAMS_DIR / f"{_slug(repo)}.jsonl"


def history(repo: str) -> list[dict]:
    """All updates in file order. Empty list if no file."""
    p = path_for(repo)
    if not p.exists():
        return []
    out: list[dict] = []
    for raw in p.read_text().splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return out


def resolved(repo: str) -> dict[str, Any]:
    """Latest value per key. The map skills/CLI consume."""
    out: dict[str, Any] = {}
    for entry in history(repo):
        k = entry.get("key")
        if k is None:
            continue
        out[k] = entry.get("value")
    return out


def append(repo: str, *, key: str, value: Any, reason: str) -> dict:
    """Append one param update. Returns the entry written."""
    entry = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "key": key,
        "value": value,
        "reason": reason,
    }
    p = path_for(repo)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps(entry, separators=(",", ":")) + "\n")
    return entry
