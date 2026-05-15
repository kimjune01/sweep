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


def _load(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text().splitlines() if line.strip()}


def has_seen(key: str) -> bool:
    """Has this prospect-key been surfaced before?"""
    return key in _load(ISSUES_FILE)


def mark_seen(key: str) -> None:
    """Append the key to the seen set. Idempotent on repeat — file is a set."""
    if has_seen(key):
        return
    SEEN_DIR.mkdir(parents=True, exist_ok=True)
    with open(ISSUES_FILE, "a") as f:
        f.write(f"{key}\n")


def filter_unseen(keys: list[str]) -> list[str]:
    """Return only keys not already in the seen set."""
    seen = _load(ISSUES_FILE)
    return [k for k in keys if k not in seen]


def issue_key(repo: str, issue: int) -> str:
    """Canonical key for a GitHub issue/PR: 'owner/repo#N'."""
    return f"{repo}#{issue}"
