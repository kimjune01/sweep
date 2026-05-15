"""Outcomes — merged/closed PRs per day. The slow KPI to optimize for.

One gh call per hour (cached). The cockpit consumes this; nothing else
should need it.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import time
from pathlib import Path

from sweep import gh_io


CACHE = Path.home() / ".sweep" / "cache" / "outcomes.json"
CACHE_TTL = 3600.0


def outcomes(days: int = 7) -> dict:
    """Fetch merged + closed-but-not-merged counts per day.

    Returns {days, user, start, end, merged, closed, merged_per_day,
    closed_per_day, fetched_at}.
    """
    if CACHE.exists():
        try:
            data = json.loads(CACHE.read_text())
            if data.get("days") == days and (time.time() - data.get("fetched_at", 0)) < CACHE_TTL:
                return data
        except (json.JSONDecodeError, OSError):
            pass

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
                fields="repository,number,updatedAt,closedAt,state",
                ttl=3600,
            )
        except subprocess.CalledProcessError:
            return []

    merged_prs = _query("merged", None)
    closed_prs = [
        pr for pr in _query("closed", "closed")
        if pr.get("state") != "MERGED"
    ]

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

    merged_per_day = _bucket_by_day(merged_prs, "updatedAt")
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
        "fetched_at": time.time(),
    }
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    try:
        CACHE.write_text(json.dumps(result))
    except OSError:
        pass
    return result


def _empty(days: int, start: dt.date, end: dt.date) -> dict:
    return {
        "days": days, "user": "",
        "start": start.isoformat(), "end": end.isoformat(),
        "merged": 0, "closed": 0,
        "merged_per_day": [0] * days, "closed_per_day": [0] * days,
        "fetched_at": time.time(),
    }
