"""Warm-orgs: orgs where we've already landed a merged PR.

Warmth is a prospect-time prioritization signal. An org with a merged PR
under our author handle is "warm" — the maintainers have seen the
username, any CLA is signed, and CI is already configured to our shape.
Cold orgs still get processed, just after warm ones in the same pass.

Cached at ~/.sweep/cache/warm_orgs.json with a 4h TTL. Merged PR history
changes slowly; refreshing more often wastes API budget.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from sweep import gh_io
from sweep.io_safe import atomic_write_text


CACHE = Path.home() / ".sweep" / "cache" / "warm_orgs.json"
CACHE_TTL = 4 * 3600.0  # 4 hours


def _refresh() -> dict:
    """Pull merged PR list from gh, count per org."""
    try:
        u = gh_io.api("user", ttl=86400)
    except subprocess.CalledProcessError:
        u = {}
    user = (u.get("login") if isinstance(u, dict) else "") or ""
    if not user:
        return {"orgs": {}, "fetched_at": time.time(), "user": ""}

    try:
        # gh CLI's --state only accepts open|closed; use the is:merged
        # query qualifier instead.
        prs = gh_io.search_prs(
            f"author:{user} is:merged",
            limit=500,
            fields="repository",
            ttl=int(CACHE_TTL),
        )
    except subprocess.CalledProcessError:
        return {"orgs": {}, "fetched_at": time.time(), "user": user}

    orgs: dict[str, int] = {}
    for pr in prs:
        full = pr.get("repository", {}).get("nameWithOwner", "")
        if "/" not in full:
            continue
        org = full.split("/", 1)[0]
        if org == user:
            continue  # self-PRs aren't a warmth signal for outreach
        orgs[org] = orgs.get(org, 0) + 1

    result = {
        "orgs": orgs,
        "fetched_at": time.time(),
        "user": user,
    }
    try:
        atomic_write_text(CACHE, json.dumps(result))
    except OSError:
        pass
    return result


def state() -> dict:
    """Read cached warm-org state, refreshing if older than TTL.

    Returns {orgs: {org_name: merged_pr_count}, fetched_at, user}.
    """
    if CACHE.exists():
        try:
            data = json.loads(CACHE.read_text())
            if time.time() - data.get("fetched_at", 0) < CACHE_TTL:
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return _refresh()


def is_warm(org: str, *, min_merged: int = 1) -> bool:
    """True if the org has >= min_merged merged PRs under our handle."""
    if not org:
        return False
    return state()["orgs"].get(org, 0) >= min_merged


def warmth(org: str) -> int:
    """Merged PR count for the org. 0 if unknown."""
    if not org:
        return 0
    return state()["orgs"].get(org, 0)
