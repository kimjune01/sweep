"""Unicode glyph helpers for the cockpit: sparklines, dither, variance dot,
time bucketization, oldest-age formatting.

Pure functions — no I/O, no globals. Importable from any subcommand.
"""

from __future__ import annotations

import datetime as dt


SPARK_CHARS = " ▁▂▃▄▅▆▇█"  # 9 levels including empty
DITHER_CHARS = " ░▒▓█"     # 5 shades — used for daily event density


# ---------------------------------------------------------- sparkline


def sparkline(counts: list[int]) -> str:
    """Render counts as a Unicode block sparkline. Peak-relative."""
    if not counts:
        return ""
    peak = max(counts) or 1
    return "".join(SPARK_CHARS[min(8, int(round(c * 8 / peak)))] for c in counts)


def sparkline_pct(counts: list[int], cap: int | None) -> str:
    """Render counts as % of cap (full block = at cap, clamped to 1.0).

    When cap is None or 0, falls back to peak-relative (sparkline).
    """
    if not counts:
        return ""
    if not cap:
        return sparkline(counts)
    return "".join(
        SPARK_CHARS[min(8, int(round(min(c / cap, 1.0) * 8)))] for c in counts
    )


# ---------------------------------------------------------- bucketize


def bucketize(timestamps: list[str], bucket_minutes: int, n_buckets: int) -> list[int]:
    """Bucket ISO 8601 timestamps into the most-recent n_buckets windows."""
    if not timestamps:
        return [0] * n_buckets
    now = dt.datetime.now(dt.timezone.utc)
    edges = [now - dt.timedelta(minutes=bucket_minutes * (n_buckets - i)) for i in range(n_buckets + 1)]
    counts = [0] * n_buckets
    for ts in timestamps:
        try:
            t = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        for i in range(n_buckets):
            if edges[i] <= t < edges[i + 1]:
                counts[i] += 1
                break
    return counts


def rate_per_hour(counts: list[int], bucket_minutes: int) -> float:
    total = sum(counts)
    hours = (len(counts) * bucket_minutes) / 60.0
    return total / hours if hours else 0.0


# ---------------------------------------------------------- dither


def dither(counts: list[int]) -> str:
    """Map counts to a 5-shade dither (' ░▒▓█'). 0→space, 1→░, 8+ → █."""
    if not counts:
        return ""
    out = []
    for c in counts:
        if c <= 0:
            out.append(DITHER_CHARS[0])
        elif c <= 2:
            out.append(DITHER_CHARS[1])
        elif c <= 4:
            out.append(DITHER_CHARS[2])
        elif c <= 7:
            out.append(DITHER_CHARS[3])
        else:
            out.append(DITHER_CHARS[4])
    return "".join(out)


# ---------------------------------------------------------- variance


def stddev(counts: list[int]) -> float:
    if len(counts) < 2:
        return 0.0
    mean = sum(counts) / len(counts)
    return (sum((c - mean) ** 2 for c in counts) / (len(counts) - 1)) ** 0.5


def variance_glyph(counts: list[int]) -> str:
    """Centered dot whose size grows with variance: ' ' · • ●."""
    if not counts or sum(counts) == 0:
        return " "
    mean = sum(counts) / len(counts)
    if mean == 0:
        return "·"
    cv = stddev(counts) / mean  # coefficient of variation — scale-free
    if cv < 0.5:
        return "·"
    if cv < 1.5:
        return "•"
    return "●"


# ---------------------------------------------------------- age


def oldest_age_str(msgs: list[dict]) -> str:
    if not msgs:
        return "—"
    now = dt.datetime.now(dt.timezone.utc)
    oldest = None
    for m in msgs:
        ts = m.get("ts", "")
        try:
            t = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if oldest is None or t < oldest:
                oldest = t
        except (ValueError, AttributeError):
            continue
    if oldest is None:
        return "—"
    secs = int((now - oldest).total_seconds())
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        return f"{secs // 3600}h"
    return f"{secs // 86400}d"
