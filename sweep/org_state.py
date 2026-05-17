"""Org-state: which GitHub orgs currently have your open PRs.

Reviews are org-gated — only one open PR per org is sustainable without
burning standing. This module tracks which orgs are "blocked" (have an
open PR awaiting review) so sift can skip them at the front of the
pipe and drip can hold pushes for them at the back.

Cached at ~/.sweep/cache/org_state.json with per-org freshness. Each
org's entry carries its own `fetched_at`; refresh is per-org via a
scoped `gh search prs --owner X` call (small, fast — much cheaper
than refetching all ~150 PRs across all orgs every TTL). After
publishing to org X we invalidate JUST X's entry; Y and Z keep
serving from cache.

The full snapshot (`state()`) is still available for display
surfaces (cockpit / waste) — it iterates known orgs, refreshing any
stale entries. Bootstrap (empty cache) does one full
`gh search prs --author=@me` call to learn the set of orgs.
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
# Per-org TTL — short because each refresh is one scoped gh call
# (small). The gate becomes effectively real-time without bandwidth
# cost: refetching just org X on a gate miss is bounded by X's PR
# count (usually <5), not by the substrate's total open PR count.
ORG_TTL = 30.0


def _user() -> str:
    """Cached gh user identity. Rarely changes; 24h TTL."""
    try:
        u = gh_io.api("user", ttl=86400)
    except subprocess.CalledProcessError:
        u = {}
    return (u.get("login") if isinstance(u, dict) else "") or ""


def _load_cache() -> dict:
    """Read whatever is on disk; tolerate missing/corrupt."""
    if not CACHE.exists():
        return {"orgs": {}, "user": ""}
    try:
        data = json.loads(CACHE.read_text())
        if "orgs" not in data:
            return {"orgs": {}, "user": data.get("user", "")}
        # Migrate from legacy snapshot shape (orgs: {X: [pr, ...]}) to
        # per-org shape (orgs: {X: {prs: [...], fetched_at: float}}).
        for org, entry in list(data["orgs"].items()):
            if isinstance(entry, list):
                # legacy: stamp with the snapshot's fetched_at (or 0)
                data["orgs"][org] = {
                    "prs": entry,
                    "fetched_at": data.get("fetched_at", 0.0),
                }
        return data
    except (json.JSONDecodeError, OSError):
        return {"orgs": {}, "user": ""}


def _save_cache(data: dict) -> None:
    try:
        atomic_write_text(CACHE, json.dumps(data))
    except OSError:
        pass


def _refresh_org(org: str, user: str) -> list[dict]:
    """Pull just this org's open PRs from gh. Scoped query — small
    response, fast. Returns the PR list (possibly empty)."""
    try:
        prs = gh_io.search_prs(
            f"author:{user} org:{org}",
            state="open",
            limit=50,
            fields="repository,number,title,updatedAt,createdAt",
            ttl=30,
        )
    except subprocess.CalledProcessError:
        return []
    out: list[dict] = []
    for pr in prs:
        full = pr.get("repository", {}).get("nameWithOwner", "")
        if "/" not in full or full.split("/", 1)[0] != org:
            continue
        out.append({
            "repo": full,
            "pr": pr.get("number"),
            "title": pr.get("title", ""),
            "updated_at": pr.get("updatedAt", ""),
            "created_at": pr.get("createdAt", ""),
        })
    return out


def _refresh_all(user: str) -> dict[str, list[dict]]:
    """One big fetch — used on bootstrap when the cache is empty and
    we don't yet know which orgs to scope per-org refreshes to."""
    try:
        prs = gh_io.search_prs(
            f"author:{user}",
            state="open",
            limit=200,
            fields="repository,number,title,updatedAt,createdAt",
            ttl=30,
        )
    except subprocess.CalledProcessError:
        return {}
    out: dict[str, list[dict]] = {}
    for pr in prs:
        full = pr.get("repository", {}).get("nameWithOwner", "")
        if "/" not in full:
            continue
        org = full.split("/", 1)[0]
        out.setdefault(org, []).append({
            "repo": full,
            "pr": pr.get("number"),
            "title": pr.get("title", ""),
            "updated_at": pr.get("updatedAt", ""),
            "created_at": pr.get("createdAt", ""),
        })
    return out


def _entry(org: str) -> dict:
    """Get org X's cache entry, refreshing if stale. Returns
    {prs: [...], fetched_at: float}. Per-org refresh on miss is the
    cheap path: one scoped gh call, bounded by X's PR count."""
    if not org:
        return {"prs": [], "fetched_at": time.time()}
    data = _load_cache()
    if not data.get("user"):
        data["user"] = _user()
    user = data["user"]
    if not user:
        return {"prs": [], "fetched_at": time.time()}
    entry = data["orgs"].get(org, {"prs": [], "fetched_at": 0.0})
    if time.time() - entry.get("fetched_at", 0.0) < ORG_TTL:
        return entry
    # Stale: refresh just this org.
    entry = {
        "prs": _refresh_org(org, user),
        "fetched_at": time.time(),
    }
    data["orgs"][org] = entry
    _save_cache(data)
    return entry


def invalidate(org: str | None = None) -> None:
    """Mark an org's cache entry stale so the next read refetches.
    Called after we create a PR so the gate doesn't approve a second
    PR to the same org during the TTL window. Passing None
    invalidates the whole cache (kept for migration compatibility;
    prefer per-org)."""
    data = _load_cache()
    if org is None:
        data["orgs"] = {}
    elif org in data.get("orgs", {}):
        data["orgs"][org]["fetched_at"] = 0.0
    _save_cache(data)


def state() -> dict:
    """Full snapshot — for display surfaces (cockpit, waste). Reads
    every known org's cached entry; refreshes any that are stale
    (per-org). Bootstrap (empty cache) does ONE full
    `gh search prs --author=@me` call to learn the set of orgs.

    Return shape stays the same as the legacy snapshot for
    backward compatibility:
      {orgs: {org_name: [pr_info, ...]}, fetched_at, user}.
    `fetched_at` is the oldest org's fetch time so callers using it
    as a global freshness signal get a conservative answer."""
    data = _load_cache()
    if not data.get("user"):
        data["user"] = _user()
    user = data["user"]
    if not user:
        return {"orgs": {}, "fetched_at": time.time(), "user": ""}
    if not data["orgs"]:
        # Cold cache: bootstrap with one full fetch.
        now = time.time()
        full = _refresh_all(user)
        data["orgs"] = {org: {"prs": prs, "fetched_at": now}
                        for org, prs in full.items()}
        _save_cache(data)
    else:
        # Warm cache: refresh just the stale orgs.
        for org, entry in list(data["orgs"].items()):
            if time.time() - entry.get("fetched_at", 0.0) >= ORG_TTL:
                data["orgs"][org] = {
                    "prs": _refresh_org(org, user),
                    "fetched_at": time.time(),
                }
        _save_cache(data)
    return {
        "orgs": {org: entry["prs"] for org, entry in data["orgs"].items()},
        "fetched_at": min((e.get("fetched_at", 0.0)
                          for e in data["orgs"].values()), default=time.time()),
        "user": user,
    }


def is_org_blocked(org: str, *, max_open_per_org: int = 1) -> bool:
    """True if the org already has the limit of open authored PRs.
    Hot path — uses per-org cache only, no fanout."""
    if not org:
        return False
    return len(_entry(org)["prs"]) >= max_open_per_org


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
