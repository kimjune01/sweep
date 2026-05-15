"""Wrapper around `gh` CLI calls with SQLite-backed TTL cache.

Same shape as llm_io but for GitHub. Read-side: cache by content hash with
short TTL. Write-side: no cache, ever (pr create, git push). The cache is
expiry-based, not forever — GitHub state moves, so a stale read is worse
than a fresh fetch.

Calling pattern:
    prs = await gh_io.search_prs(f"author:@me is:open", ttl=60)
    state = await gh_io.pr_view("hyperium/hyper", 4068, ttl=60)

Forensics: every cache hit / miss is timestamped in ~/.sweep/cache/gh.db.
Easy to ask "how many gh calls did this prospect run actually fire" by
diffing row counts before/after.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path


DB_PATH = Path.home() / ".sweep" / "cache" / "gh.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS gh_cache (
    key         TEXT PRIMARY KEY,
    endpoint    TEXT NOT NULL,
    args        TEXT NOT NULL,
    response    TEXT NOT NULL,
    fetched_at  TEXT NOT NULL,
    ttl_seconds INTEGER NOT NULL,
    expires_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_expires  ON gh_cache(expires_at);
CREATE INDEX IF NOT EXISTS idx_endpoint ON gh_cache(endpoint);
"""


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript(_SCHEMA)
    return conn


def _key(endpoint: str, args: list[str]) -> str:
    return hashlib.sha256(f"{endpoint}|{json.dumps(args)}".encode()).hexdigest()


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _cache_get(key: str) -> str | None:
    now = _now().isoformat()
    with _conn() as conn:
        row = conn.execute(
            "SELECT response FROM gh_cache WHERE key = ? AND expires_at > ?",
            (key, now),
        ).fetchone()
    return row[0] if row else None


def _cache_put(key: str, endpoint: str, args: list[str],
               response: str, ttl: int) -> None:
    fetched_at = _now()
    expires_at = fetched_at + dt.timedelta(seconds=ttl)
    with _conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO gh_cache
               (key, endpoint, args, response, fetched_at, ttl_seconds, expires_at)
               VALUES (?,?,?,?,?,?,?)""",
            (key, endpoint, json.dumps(args), response,
             fetched_at.isoformat(), ttl, expires_at.isoformat()),
        )
        conn.commit()


def _gh(args: list[str]) -> str:
    """Run `gh ARGS`, return stdout. Non-zero exit raises subprocess.CalledProcessError."""
    out = subprocess.run(["gh"] + args, capture_output=True, text=True, check=False)
    if out.returncode != 0:
        raise subprocess.CalledProcessError(
            out.returncode, ["gh"] + args, output=out.stdout, stderr=out.stderr,
        )
    return out.stdout


def _cached_json(endpoint: str, args: list[str], ttl: int) -> list | dict:
    key = _key(endpoint, args)
    hit = _cache_get(key)
    if hit is not None:
        try:
            return json.loads(hit)
        except json.JSONDecodeError:
            pass  # corrupt cache row — refetch
    raw = _gh(args)
    try:
        parsed = json.loads(raw) if raw.strip() else []
    except json.JSONDecodeError:
        parsed = []
    _cache_put(key, endpoint, args, json.dumps(parsed), ttl)
    return parsed


# ------------------------------------------------------------ public API


async def search_repos(query: str, *, sort: str = "stars", order: str = "desc",
                        limit: int = 30, fields: str | None = None,
                        ttl: int = 600) -> list[dict]:
    args = ["search", "repos", query,
            "--sort", sort, "--order", order, "--limit", str(limit),
            "--json", fields or "fullName,stargazersCount,openIssuesCount,pushedAt,isArchived,description"]
    return _cached_json("search_repos", args, ttl)


async def search_issues(query: str, *, limit: int = 30,
                        fields: str | None = None, ttl: int = 120) -> list[dict]:
    args = ["search", "issues", query, "--limit", str(limit),
            "--json", fields or "number,title,url,labels,updatedAt,repository"]
    return _cached_json("search_issues", args, ttl)


async def search_prs(query: str, *, state: str | None = None, limit: int = 30,
                      fields: str | None = None, ttl: int = 60) -> list[dict]:
    args = ["search", "prs", query, "--limit", str(limit),
            "--json", fields or "repository,number,title,url,createdAt,updatedAt,author,state"]
    if state:
        args = args[:-2] + ["--state", state] + args[-2:]
    return _cached_json("search_prs", args, ttl)


async def pr_view(repo: str, pr: int, *,
                  fields: str | None = None, ttl: int = 60) -> dict:
    if "/" not in repo:
        raise ValueError(f"repo must be owner/repo, got {repo!r}")
    args = ["pr", "view", str(pr), "--repo", repo, "--json",
            fields or "state,mergeable,reviewDecision,reviews,statusCheckRollup,"
                     "isDraft,comments,headRefName,updatedAt,title,url"]
    result = _cached_json("pr_view", args, ttl)
    return result if isinstance(result, dict) else {}


async def pr_list(repo: str, *, state: str = "open", limit: int = 30,
                   search: str | None = None,
                   fields: str | None = None, ttl: int = 60) -> list[dict]:
    args = ["pr", "list", "--repo", repo, "--state", state,
            "--limit", str(limit), "--json",
            fields or "number,title,author,state,mergedAt,closedAt,updatedAt"]
    if search:
        args += ["--search", search]
    return _cached_json("pr_list", args, ttl)


async def issue_view(repo: str, issue: int, *,
                      fields: str | None = None, ttl: int = 300) -> dict:
    args = ["issue", "view", str(issue), "--repo", repo, "--json",
            fields or "number,title,body,labels,state,author,createdAt,updatedAt,comments"]
    result = _cached_json("issue_view", args, ttl)
    return result if isinstance(result, dict) else {}


async def issue_events(repo: str, issue: int, *, ttl: int = 300) -> list[dict]:
    """Cross-reference + label + assignment events. Used for dedup-against-PRs."""
    args = ["api", f"repos/{repo}/issues/{issue}/events", "--paginate"]
    return _cached_json("issue_events", args, ttl)


async def pr_inline_comments(repo: str, pr: int, *, ttl: int = 120) -> list[dict]:
    """Inline (code-line) review comments on a PR.

    Distinct from issue-conversation comments. These are the threaded
    comments anchored to specific diff lines — load-bearing for the Sonnet
    'is this respondable' classifier since they're often the substantive
    review surface (maintainers leave 'consider X' on a specific line
    rather than a top-level review).
    """
    args = ["api", f"repos/{repo}/pulls/{pr}/comments", "--paginate"]
    return _cached_json("pr_inline_comments", args, ttl)


async def api(path: str, *, paginate: bool = False, ttl: int = 300) -> list | dict:
    """Raw REST API call. For endpoints not covered by typed methods above."""
    args = ["api", path]
    if paginate:
        args.append("--paginate")
    return _cached_json("api", args, ttl)


async def api_graphql(query: str, *, ttl: int = 300) -> dict:
    args = ["api", "graphql", "-f", f"query={query}"]
    result = _cached_json("api_graphql", args, ttl)
    return result if isinstance(result, dict) else {}


# ------------------------------------------------------------ forensics


def cache_stats() -> dict:
    """Counts by endpoint + total live rows. For 'how busy is our gh cache.'"""
    now = _now().isoformat()
    with _conn() as conn:
        rows = conn.execute(
            """SELECT endpoint, COUNT(*) AS n,
                      SUM(CASE WHEN expires_at > ? THEN 1 ELSE 0 END) AS live
               FROM gh_cache GROUP BY endpoint""",
            (now,),
        ).fetchall()
    return {ep: {"total": n, "live": live} for ep, n, live in rows}


def purge_expired() -> int:
    """Drop expired rows. Returns count deleted."""
    now = _now().isoformat()
    with _conn() as conn:
        cur = conn.execute("DELETE FROM gh_cache WHERE expires_at < ?", (now,))
        conn.commit()
        return cur.rowcount
