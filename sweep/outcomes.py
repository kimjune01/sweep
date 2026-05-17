"""Outcomes — merged/closed PRs in the last N days, plus the underlying records.

One gh call per hour (cached). Two consumers:
  - cockpit reads the daily counts (merged_per_day, closed_per_day);
  - retro reads the per-PR records (merged_records, closed_records) to
    feed RETRO_GRAPH.md and the pipeline-level HYPOTHESIS_GRAPH.md
    (one entry per PR outcome, classified against H0..HN).
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import time
from pathlib import Path

from sweep import gh_io
from sweep.io_safe import atomic_write_text


CACHE = Path.home() / ".sweep" / "cache" / "outcomes.json"
CACHE_TTL = 3600.0


def _load_store() -> dict[str, dict]:
    if not CACHE.exists():
        return {}
    try:
        raw = json.loads(CACHE.read_text())
        if not isinstance(raw, dict):
            return {}
        if "days" in raw and "fetched_at" in raw:
            return {str(raw["days"]): raw}
        return {str(k): v for k, v in raw.items() if isinstance(v, dict)}
    except (json.JSONDecodeError, OSError):
        return {}


def outcomes(days: int = 7) -> dict:
    """Stale-while-revalidate read: return whatever's cached for this
    `days` value instantly, and if it's stale, kick a background
    subprocess to refresh. Next call sees the new value.

    Display surfaces (wasteboard) cycle through this many times per
    operator session — blocking even once for 7s is the kind of lag
    that breaks the TUI. By contrast, a slightly-stale outcomes view
    is invisible: the daily buckets don't move minute-to-minute.

    First-ever call returns an empty result so callers don't have to
    handle None; the warmer fills in subsequent calls.
    """
    store = _load_store()
    end = dt.datetime.now(dt.timezone.utc).date()
    start = end - dt.timedelta(days=days - 1)
    hit = store.get(str(days))

    stale = not hit or (time.time() - hit.get("fetched_at", 0)) >= CACHE_TTL
    if stale:
        _spawn_warmer(days)

    if hit:
        return hit
    return _empty(days, start, end)


def _spawn_warmer(days: int) -> None:
    """Fire-and-forget background refresh. Detaches from the parent
    so the CLI / TUI doesn't wait. If a warmer is already running for
    this `days` (lockfile present), no-op."""
    import sys
    lock = CACHE.parent / f".outcomes-warmer-{days}.lock"
    if lock.exists():
        # Honor a stale lock after 5 min — otherwise a crashed warmer
        # would block warming forever.
        try:
            if time.time() - lock.stat().st_mtime < 300:
                return
        except OSError:
            pass
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.touch()
    except OSError:
        pass
    try:
        subprocess.Popen(
            [sys.executable, "-m", "sweep.outcomes", "warm", str(days)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, start_new_session=True,
        )
    except OSError:
        try:
            lock.unlink()
        except OSError:
            pass


def _refresh(days: int) -> dict:
    """Synchronous refresh — what the background warmer actually runs.
    Holds the lock for the duration; clears it on exit."""
    store = _load_store()
    end = dt.datetime.now(dt.timezone.utc).date()
    start = end - dt.timedelta(days=days - 1)

    try:
        u = gh_io.api("user", ttl=86400)  # identity rarely changes
    except subprocess.CalledProcessError:
        u = {}
    user = (u.get("login") if isinstance(u, dict) else "") or ""
    if not user:
        return _empty(days, start, end)

    def _query(date_qualifier: str, state: str | None) -> list[dict]:
        query = f"author:{user} {date_qualifier}:>={start.isoformat()}"
        try:
            return gh_io.search_prs(
                query,
                state=state,
                limit=200,
                fields="repository,number,title,url,closedAt,updatedAt,state",
                ttl=3600,
            )
        except subprocess.CalledProcessError:
            return []

    merged_prs = _query("merged", None)
    # gh's --state closed returns merged PRs too, and the response's
    # state field shape doesn't reliably read as "MERGED" for filtering.
    # Dedupe by (repo, number) against the merged set instead.
    merged_keys = {
        (pr.get("repository", {}).get("nameWithOwner", ""), pr.get("number"))
        for pr in merged_prs
    }
    closed_prs = [
        pr for pr in _query("closed", "closed")
        if (pr.get("repository", {}).get("nameWithOwner", ""), pr.get("number"))
        not in merged_keys
    ]

    def _record(pr: dict, outcome: str) -> dict:
        full = pr.get("repository", {}).get("nameWithOwner", "")
        return {
            "repo": full,
            "number": pr.get("number"),
            "title": pr.get("title", ""),
            "url": pr.get("url", ""),
            "closed_at": pr.get("closedAt", ""),
            "outcome": outcome,  # "merged" | "closed"
        }

    merged_records = [_record(pr, "merged") for pr in merged_prs]
    closed_records = [_record(pr, "closed") for pr in closed_prs]

    def _bucket_by_day(prs: list[dict], date_key: str) -> list[int]:
        counts = [0] * days
        for pr in prs:
            ts = pr.get(date_key) or pr.get("updatedAt") or ""
            try:
                t = dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).date()
            except (ValueError, AttributeError):
                continue
            idx = (t - start).days
            if 0 <= idx < days:
                counts[idx] += 1
        return counts

    # Merge date != update date: post-merge automation (CI, bot labels,
    # auto-close of linked issues) bumps updatedAt past the actual merge
    # day. For merged PRs, closedAt IS the merge timestamp (gh search prs
    # exposes closedAt but not mergedAt; merge sets both close+merge in
    # one transaction). Bucket by closedAt so the daily counts reflect
    # when the work landed, not when the followup ran.
    merged_per_day = _bucket_by_day(merged_prs, "closedAt")
    closed_per_day = _bucket_by_day(closed_prs, "closedAt")

    result = {
        "days": days,
        "user": user,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "merged": sum(merged_per_day),
        "closed": sum(closed_per_day),
        "merged_per_day": merged_per_day,
        "closed_per_day": closed_per_day,
        "merged_records": merged_records,
        "closed_records": closed_records,
        "fetched_at": time.time(),
    }
    store[str(days)] = result
    try:
        atomic_write_text(CACHE, json.dumps(store))
    except OSError:
        pass
    return result


def _empty(days: int, start: dt.date, end: dt.date) -> dict:
    return {
        "days": days, "user": "",
        "start": start.isoformat(), "end": end.isoformat(),
        "merged": 0, "closed": 0,
        "merged_per_day": [0] * days, "closed_per_day": [0] * days,
        "merged_records": [], "closed_records": [],
        # fetched_at=0 so the next read treats this placeholder as
        # stale and re-kicks the warmer (the first kick may have
        # crashed; don't wedge on a never-warmed slot).
        "fetched_at": 0.0,
    }


if __name__ == "__main__":
    # Background warmer entrypoint: `python -m sweep.outcomes warm N`.
    # Holds the lock for its lifetime; clears it on exit.
    import sys
    if len(sys.argv) >= 3 and sys.argv[1] == "warm":
        days = int(sys.argv[2])
        lock = CACHE.parent / f".outcomes-warmer-{days}.lock"
        try:
            _refresh(days)
        finally:
            try:
                lock.unlink()
            except OSError:
                pass


def recent_merged_records(days: int = 7, *, repo: str | None = None) -> list[dict]:
    """PR records (repo, number, title, url, closed_at, outcome) for PRs
    merged in the last `days`. Filter to one repo with `repo="owner/name"`."""
    recs = outcomes(days).get("merged_records", [])
    return [r for r in recs if not repo or r.get("repo") == repo]


def recent_closed_records(days: int = 7, *, repo: str | None = None) -> list[dict]:
    """PR records for PRs closed-unmerged in the last `days`."""
    recs = outcomes(days).get("closed_records", [])
    return [r for r in recs if not repo or r.get("repo") == repo]


def recent_records(days: int = 7, *, repo: str | None = None) -> list[dict]:
    """Both merged and closed records, sorted by closed_at descending."""
    recs = recent_merged_records(days, repo=repo) + recent_closed_records(days, repo=repo)
    recs.sort(key=lambda r: r.get("closed_at", ""), reverse=True)
    return recs
