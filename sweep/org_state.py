"""Org-state: which GitHub orgs currently have your open PRs.

Reviews are org-gated — only one open PR per org is sustainable without
burning standing. This module tracks which orgs are "blocked" (have an
open PR awaiting review) so sift can skip them at the front of the
pipe and drip can hold pushes for them at the back.

Cached at ~/.sweep/cache/org_state.json with a 5 min TTL. Orgs unblock
when PRs merge or close upstream — we don't need second-by-second
freshness, but stale data > 5 min would let sift surface issues
from orgs that drained while we were sweeping.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import time
from pathlib import Path

from sweep import gh_io
from sweep.io_safe import atomic_write_text


CACHE = Path.home() / ".sweep" / "cache" / "org_state.json"
CACHE_TTL = 30.0  # 30s — must be shorter than the substrate's
                  # PR-creation cadence, else the org gate becomes
                  # advisory. The original 5-min TTL let two PRs land
                  # in kimjune01/sptlrx 4m25s apart (cache showed 0
                  # at both gate checks because it was stale by
                  # construction). Combine with invalidate() called
                  # after we create a PR — write-through closes the
                  # remaining race within the 30s window.


def _refresh() -> dict:
    """Pull open PR list from gh, group by org."""
    try:
        u = gh_io.api("user", ttl=86400)  # identity rarely changes
    except subprocess.CalledProcessError:
        u = {}
    user = (u.get("login") if isinstance(u, dict) else "") or ""
    if not user:
        return {"orgs": {}, "fetched_at": time.time(), "user": ""}

    try:
        prs = gh_io.search_prs(
            f"author:{user}",
            state="open",
            limit=200,
            fields="repository,number,title,updatedAt,createdAt",
            ttl=300,
        )
    except subprocess.CalledProcessError:
        return {"orgs": {}, "fetched_at": time.time(), "user": user}

    orgs: dict[str, list[dict]] = {}
    for pr in prs:
        full = pr.get("repository", {}).get("nameWithOwner", "")
        if "/" not in full:
            continue
        org = full.split("/", 1)[0]
        orgs.setdefault(org, []).append({
            "repo": full,
            "pr": pr.get("number"),
            "title": pr.get("title", ""),
            "updated_at": pr.get("updatedAt", ""),
            "created_at": pr.get("createdAt", ""),
        })

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


def invalidate() -> None:
    """Force the next state() call to refetch. Called after we create
    a PR so the next gate check sees the new state immediately,
    closing the cache-staleness race window. The gh search itself
    will see the new PR within a few seconds of `gh pr create`
    returning."""
    try:
        if CACHE.exists():
            CACHE.unlink()
    except OSError:
        pass


def state() -> dict:
    """Read cached org-state, refreshing if older than TTL.

    Returns {orgs: {org_name: [pr_info, ...]}, fetched_at, user}.
    """
    if CACHE.exists():
        try:
            data = json.loads(CACHE.read_text())
            if time.time() - data.get("fetched_at", 0) < CACHE_TTL:
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return _refresh()


def is_org_blocked(org: str, *, max_open_per_org: int = 1) -> bool:
    """True if the org already has the limit of open authored PRs."""
    if not org:
        return False
    return len(state()["orgs"].get(org, [])) >= max_open_per_org


def org_of(repo: str) -> str:
    """Extract org from owner/repo. Returns '' if malformed."""
    return repo.split("/", 1)[0] if "/" in repo else ""


def blocked_orgs(max_open_per_org: int = 1) -> dict[str, list[dict]]:
    """All orgs currently at or over the cap, with their open PRs."""
    return {
        org: prs
        for org, prs in state()["orgs"].items()
        if len(prs) >= max_open_per_org
    }
