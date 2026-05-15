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

    user = subprocess.run(
        ["gh", "api", "user", "--jq", ".login"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    if not user:
        return _empty(days, start, end)

    def _query(date_field: str, extra_filters: list[str]) -> list[dict]:
        out = subprocess.run(
            [
                "gh", "search", "prs",
                "--author", user,
                f"--{date_field}", f">={start.isoformat()}",
                *extra_filters,
                "--limit", "200",
                "--json", "repository,number,updatedAt,closedAt,state",
            ],
            capture_output=True, text=True, check=False,
        )
        try:
            return json.loads(out.stdout or "[]")
        except json.JSONDecodeError:
            return []

    merged_prs = _query("merged-at", [])
    closed_prs = [
        pr for pr in _query("closed", ["--state", "closed"])
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
