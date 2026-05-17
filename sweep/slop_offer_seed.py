"""Side-channel seed file for slop-offer candidates.

Sift drops repos with hostile AI policies from the contribution
funnel. Those same repos are warm targets for the slop-offer pipeline
(they've already publicly committed to the framing). Rather than calling
offer-slop-filter inline from the sift hot path, sift appends
to this seed file; the next `slop-offer tick` pulls candidates from
both dep-pool and the seed file, dedupes, and queues passing rows.

Append-only plain text, one owner/repo per line. dep-pool reads it on
demand. Fail-soft: any IO error here must never break sift.
"""
from __future__ import annotations

from pathlib import Path

SEED = Path.home() / ".sweep" / "inbox" / "slop_offer_seeds.txt"


def append(repo: str) -> None:
    """Append `repo` to the seed file. Swallow all errors."""
    try:
        SEED.parent.mkdir(parents=True, exist_ok=True)
        with SEED.open("a") as f:
            f.write(repo + "\n")
    except Exception:
        pass


def read_unique() -> list[str]:
    """Return deduped repos from the seed file. Empty if missing."""
    if not SEED.exists():
        return []
    seen: dict[str, None] = {}
    try:
        for line in SEED.read_text().splitlines():
            r = line.strip()
            if r and "/" in r:
                seen.setdefault(r)
    except Exception:
        return []
    return list(seen.keys())
