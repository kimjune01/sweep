"""Org-state: which GitHub orgs currently have your open PRs.

Reviews are org-gated — only one open PR per org is sustainable without
burning standing. This module tracks which orgs are "blocked" (have an
open PR awaiting review) so sift can skip them at the front of the
pipe and drip can hold pushes for them at the back.

Architecture: pure cache reads; writes refresh from gh explicitly.

- All readers (state, is_org_blocked) hit ~/.sweep/cache/org_state.json
  and never block on network. A stale cache reads as stale; the
  display surfaces show the cache's age. Reads never trigger refresh.
- Writers (publishers) call `refresh_org(org)` after they ship a PR,
  re-fetching that one org via scoped `gh search prs --owner X` and
  updating the cache atomically. The next gate read sees the new PR
  immediately — no race window, no TTL to wait out.
- Cold bootstrap: `refresh_all()` does one big `gh search prs
  --author=@me` and seeds the cache. Called from sweep startup and
  on operator demand (`sweep refresh-orgs`).

The TTL field on each entry is informational only — it tells display
surfaces how old the cache is so the operator can spot bit-rot.
Reads do not act on it.
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
# How long the background refresher waits before re-fetching the
# full org set. Reads do NOT consult this — they only read cache.
# This bounds how stale display surfaces can get when no writes
# have happened to refresh things naturally.
BG_REFRESH_TTL = 15 * 60.0


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
    response, fast. Returns the PR list (possibly empty). isDraft is
    captured so the gate can exclude drafts from its count — a parked
    draft doesn't burn maintainer review attention."""
    try:
        prs = gh_io.search_prs(
            f"author:{user} org:{org}",
            state="open",
            limit=50,
            fields="repository,number,title,updatedAt,createdAt,isDraft",
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
            "is_draft": bool(pr.get("isDraft", False)),
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
            fields="repository,number,title,updatedAt,createdAt,isDraft",
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
            "is_draft": bool(pr.get("isDraft", False)),
        })
    return out


def _entry(org: str) -> dict:
    """Read org X's cache entry. Pure cache read — never refreshes.
    Returns {prs: [], fetched_at: 0.0} if the org isn't cached yet.
    Callers that need fresh data must call refresh_org() first."""
    if not org:
        return {"prs": [], "fetched_at": 0.0}
    data = _load_cache()
    return data.get("orgs", {}).get(org, {"prs": [], "fetched_at": 0.0})


def refresh_org(org: str) -> dict:
    """Re-fetch one org from gh and write to cache. Returns the new
    entry. Call this after publishing a PR so the gate sees the new
    open PR immediately without a stale-cache race. Per-org refresh
    is cheap (one scoped gh call, bounded by X's PR count)."""
    if not org:
        return {"prs": [], "fetched_at": time.time()}
    data = _load_cache()
    if not data.get("user"):
        data["user"] = _user()
    user = data["user"]
    if not user:
        return {"prs": [], "fetched_at": time.time()}
    entry = {"prs": _refresh_org(org, user), "fetched_at": time.time()}
    data["orgs"][org] = entry
    _save_cache(data)
    return entry


def refresh_if_stale() -> bool:
    """Called from background tickers (sift). No-op if cache's
    oldest entry is younger than BG_REFRESH_TTL; otherwise refreshes
    the full set. Returns True if a refresh ran."""
    data = _load_cache()
    orgs = data.get("orgs", {})
    oldest = min((e.get("fetched_at", 0.0) for e in orgs.values()),
                 default=0.0)
    if orgs and time.time() - oldest < BG_REFRESH_TTL:
        return False
    refresh_all()
    return True


def refresh_all() -> dict[str, list[dict]]:
    """One big `gh search prs --author=@me` to learn the full set of
    orgs and seed the cache. Used at sweep startup and on operator
    demand (`sweep refresh-orgs`). Returns the new orgs map."""
    data = _load_cache()
    if not data.get("user"):
        data["user"] = _user()
    user = data["user"]
    if not user:
        return {}
    now = time.time()
    full = _refresh_all(user)
    data["orgs"] = {org: {"prs": prs, "fetched_at": now}
                    for org, prs in full.items()}
    _save_cache(data)
    return full


def state() -> dict:
    """Pure cache read. Never fetches from gh. Empty until
    `refresh_all()` seeds it (sweep startup) or `refresh_org()` warms
    individual entries (post-publish writes).

    Return shape stays the same as the legacy snapshot:
      {orgs: {org_name: [pr_info, ...]}, fetched_at, user}.
    `fetched_at` is the oldest org's fetch time so display surfaces
    can show how stale the cache is.
    """
    data = _load_cache()
    user = data.get("user", "")
    orgs = data.get("orgs", {})
    return {
        "orgs": {org: entry["prs"] for org, entry in orgs.items()},
        "fetched_at": min((e.get("fetched_at", 0.0)
                          for e in orgs.values()), default=0.0),
        "user": user,
    }


def _ready_prs(prs: list[dict]) -> list[dict]:
    """Drafts are parked and don't burn maintainer review attention,
    so they don't count toward the org gate's cap. A repo with one
    draft and zero ready PRs is at the gate as far as the substrate
    is concerned — fine to open a new ready PR there."""
    return [p for p in prs if not p.get("is_draft", False)]


def is_org_blocked(org: str, *, max_open_per_org: int = 1) -> bool:
    """True if the org already has the limit of open NON-DRAFT
    authored PRs. Pure cache read. Publishers must refresh_org(org)
    after creating a PR so the next gate check sees the new state."""
    if not org:
        return False
    return len(_ready_prs(_entry(org)["prs"])) >= max_open_per_org


def org_of(repo: str) -> str:
    """Extract org from owner/repo. Returns '' if malformed."""
    return repo.split("/", 1)[0] if "/" in repo else ""


def blocked_orgs(max_open_per_org: int = 1) -> dict[str, list[dict]]:
    """All orgs currently at or over the cap (non-draft PRs only)."""
    return {
        org: _ready_prs(prs)
        for org, prs in state()["orgs"].items()
        if len(_ready_prs(prs)) >= max_open_per_org
    }
