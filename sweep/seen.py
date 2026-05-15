"""Dedup for prospect → triage handoff.

Prospect surfaces issues; triage consumes them. Without dedup, prospect
re-discovers the same issue on every scan and triage scores it again.

We use a plain set in a file (`~/.sweep/seen/issues.txt`) rather than a
bloom filter. At our scale — thousands of issues max — the set is small
enough that linear lookup is cheap, and we want zero false positives
(a real bloom filter would occasionally claim an unseen issue was seen
and silently drop work).

Bloom-filter migration trigger: when seen.txt grows past ~100k entries,
swap in `pybloom-live` or similar with a known false-positive rate.
"""

from __future__ import annotations

from pathlib import Path


SEEN_DIR = Path.home() / ".sweep" / "seen"
ISSUES_FILE = SEEN_DIR / "issues.txt"


# Process-lifetime cache of the seen set. Lazy-loaded on first access.
# Reloaded if the underlying file's mtime changes (another process appended).
# O(1) membership lookup; the file is the durable form, the set is the index.
_cache: set[str] | None = None
_cache_mtime: float = 0.0


def _seen() -> set[str]:
    global _cache, _cache_mtime
    if not ISSUES_FILE.exists():
        if _cache is None:
            _cache = set()
            _cache_mtime = 0.0
        return _cache
    mtime = ISSUES_FILE.stat().st_mtime
    if _cache is None or mtime > _cache_mtime:
        _cache = {
            line.strip()
            for line in ISSUES_FILE.read_text().splitlines()
            if line.strip()
        }
        _cache_mtime = mtime
    return _cache


def has_seen(key: str) -> bool:
    """O(1) — set membership against the cached seen set."""
    return key in _seen()


def mark_seen(key: str) -> None:
    """Append to the file; update the cache in place. O(1)."""
    s = _seen()
    if key in s:
        return
    SEEN_DIR.mkdir(parents=True, exist_ok=True)
    with open(ISSUES_FILE, "a") as f:
        f.write(f"{key}\n")
    s.add(key)
    # Keep cache mtime in sync with the file we just wrote.
    global _cache_mtime
    _cache_mtime = ISSUES_FILE.stat().st_mtime
    # Counter — retro reads this to estimate prospect's surface-area growth.
    # Local import: seen is a leaf module and observe must not pull it in.
    from sweep import observe
    observe.incr("seen_add")


def filter_unseen(keys: list[str]) -> list[str]:
    """Return only keys not already seen. O(n) on input, O(1) per check."""
    s = _seen()
    return [k for k in keys if k not in s]


def issue_key(repo: str, issue: int) -> str:
    """Canonical key for a GitHub issue/PR: 'owner/repo#N'."""
    return f"{repo}#{issue}"
