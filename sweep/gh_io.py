"""Wrapper around `gh` CLI calls with SQLite-backed TTL cache.

Same shape as llm_io but for GitHub. Read-side: cache by content hash with
short TTL. Write-side: no cache, ever (pr create, git push). The cache is
expiry-based, not forever — GitHub state moves, so a stale read is worse
than a fresh fetch.

Calling pattern:
    prs = gh_io.search_prs(f"author:@me is:open", ttl=60)
    state = gh_io.pr_view("hyperium/hyper", 4068, ttl=60)

Functions are synchronous — the underlying work is just subprocess + sqlite,
nothing to await. Activities call them directly; Temporal runs activities on
a worker thread pool so blocking on subprocess inside an activity is fine.

Forensics: every cache hit / miss is timestamped in ~/.sweep/cache/gh.db.
Easy to ask "how many gh calls did this prospect run actually fire" by
diffing row counts before/after.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import shlex
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path


def _split_query(query: str) -> list[str]:
    """Split a search-query string into separate argv tokens.

    `gh search` treats each positional as one qualifier; combining them into
    a single quoted string makes gh see the whole thing as the value of the
    first qualifier (e.g. `gh search prs "author:X merged:>=Y"` → the API
    receives `author:"X merged:>=Y"`, which matches nothing).

    shlex preserves quoted spans, so `label:"good first issue","help wanted"`
    becomes one token whose interior spaces survive.
    """
    return shlex.split(query) if query else []


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
    from sweep import observe  # local import — observe imports nothing from gh_io

    key = _key(endpoint, args)
    hit = _cache_get(key)
    if hit is not None:
        try:
            parsed = json.loads(hit)
        except json.JSONDecodeError:
            parsed = None  # corrupt cache row — fall through to refetch
        if parsed is not None:
            observe.incr(f"gh_hit:{endpoint}")
            return parsed
    observe.incr(f"gh_miss:{endpoint}")
    raw = _gh(args)
    try:
        parsed = json.loads(raw) if raw.strip() else []
    except json.JSONDecodeError:
        parsed = []
    _cache_put(key, endpoint, args, json.dumps(parsed), ttl)
    return parsed


# ------------------------------------------------------------ public API


def search_repos(query: str, *, sort: str = "stars", order: str = "desc",
                  limit: int = 30, fields: str | None = None,
                  ttl: int = 600) -> list[dict]:
    args = ["search", "repos", *_split_query(query),
            "--sort", sort, "--order", order, "--limit", str(limit),
            "--json", fields or "fullName,stargazersCount,openIssuesCount,pushedAt,isArchived,description"]
    return _cached_json("search_repos", args, ttl)


def search_prs(query: str, *, state: str | None = None, limit: int = 30,
                fields: str | None = None, ttl: int = 60) -> list[dict]:
    args = ["search", "prs", *_split_query(query), "--limit", str(limit),
            "--json", fields or "repository,number,title,url,createdAt,updatedAt,author,state"]
    if state:
        args = args[:-2] + ["--state", state] + args[-2:]
    return _cached_json("search_prs", args, ttl)


def search_issues(*, labels: list[str] | None = None,
                  state: str = "open",
                  no_assignee: bool = True,
                  archived: bool | None = False,
                  created_after: str | None = None,
                  owner: str | None = None,
                  sort: str = "updated", order: str = "desc",
                  limit: int = 100, ttl: int = 1800) -> list[dict]:
    """`gh search issues` wrapper, JSON-shaped. gh refuses inline
    qualifiers like `label:bug` in the positional query — those have
    to be passed as flags (--label bug). Build the arg list flag-form."""
    args = ["search", "issues"]
    if labels:
        args += ["--label", ",".join(labels)]
    if state:
        args += ["--state", state]
    if no_assignee:
        args += ["--no-assignee"]
    if archived is not None:
        args += ["--archived", "true" if archived else "false"]
    if created_after:
        args += ["--created", f">={created_after}"]
    if owner:
        args += ["--owner", owner]
    args += ["--sort", sort, "--order", order,
             "--limit", str(limit),
             "--json", "repository,number,title,labels,url,updatedAt,createdAt,state,body,author,commentsCount,assignees"]
    result = _cached_json("search_issues", args, ttl)
    return result if isinstance(result, list) else []


def pr_view(repo: str, pr: int, *,
             fields: str | None = None, ttl: int = 60) -> dict:
    if "/" not in repo:
        raise ValueError(f"repo must be owner/repo, got {repo!r}")
    args = ["pr", "view", str(pr), "--repo", repo, "--json",
            fields or "state,mergeable,reviewDecision,reviews,statusCheckRollup,"
                     "isDraft,comments,headRefName,updatedAt,title,url,author"]
    result = _cached_json("pr_view", args, ttl)
    return result if isinstance(result, dict) else {}


def pr_list(repo: str, *, state: str = "open", limit: int = 30,
             search: str | None = None,
             fields: str | None = None, ttl: int = 60) -> list[dict]:
    args = ["pr", "list", "--repo", repo, "--state", state,
            "--limit", str(limit), "--json",
            fields or "number,title,author,state,mergedAt,closedAt,updatedAt"]
    if search:
        args += ["--search", search]
    return _cached_json("pr_list", args, ttl)


def issue_view(repo: str, issue: int, *,
                fields: str | None = None, ttl: int = 300) -> dict:
    args = ["issue", "view", str(issue), "--repo", repo, "--json",
            fields or "number,title,body,labels,state,author,createdAt,updatedAt,comments"]
    result = _cached_json("issue_view", args, ttl)
    return result if isinstance(result, dict) else {}


def issue_events(repo: str, issue: int, *, ttl: int = 300) -> list[dict]:
    """Cross-reference + label + assignment events. Used for dedup-against-PRs."""
    args = ["api", f"repos/{repo}/issues/{issue}/events", "--paginate"]
    return _cached_json("issue_events", args, ttl)


def pr_inline_comments(repo: str, pr: int, *, ttl: int = 120) -> list[dict]:
    """Inline (code-line) review comments on a PR.

    Distinct from issue-conversation comments. These are the threaded
    comments anchored to specific diff lines — load-bearing for the Sonnet
    'is this respondable' classifier since they're often the substantive
    review surface (maintainers leave 'consider X' on a specific line
    rather than a top-level review).
    """
    args = ["api", f"repos/{repo}/pulls/{pr}/comments", "--paginate"]
    return _cached_json("pr_inline_comments", args, ttl)


def api(path: str, *, paginate: bool = False, ttl: int = 300) -> list | dict:
    """Raw REST API call. For endpoints not covered by typed methods above."""
    args = ["api", path]
    if paginate:
        args.append("--paginate")
    return _cached_json("api", args, ttl)


def api_graphql(query: str, *, ttl: int = 300) -> dict:
    args = ["api", "graphql", "-f", f"query={query}"]
    result = _cached_json("api_graphql", args, ttl)
    return result if isinstance(result, dict) else {}


def repo_ai_policy(repo: str, *, ttl: int = 24 * 3600) -> str:
    """Probe AGENTS.md / CONTRIBUTING for explicit AI-tool policies.

    Returns one of:
      "hostile"    — file mentions "no AI" / "no LLM" / "AI-generated PRs forbidden"
      "required"   — file requires AI disclosure (we comply by default)
      "permissive" — file present, no restrictions
      "unknown"    — no file found or unreadable

    Cached aggressively (24h default) because policies don't change daily
    and we don't want to redo it for every issue from the same repo.
    """
    if "/" not in repo:
        return "unknown"
    # AGENTS.md first (the emerging convention), then CONTRIBUTING.md.
    # NOTE: this path is uncached — _cached_json only serializes JSON
    # bodies, and these endpoints return raw markdown. The docstring's
    # 24h cache claim refers to the intended behavior; making it real
    # requires a _cached_text variant (TODO). Today every call hits gh.
    for path in ("AGENTS.md", "CONTRIBUTING.md", "CONTRIBUTING.rst"):
        try:
            text = _gh(["api", f"repos/{repo}/contents/{path}",
                        "-H", "Accept: application/vnd.github.raw"])
        except subprocess.CalledProcessError:
            continue
        if not text or text.startswith("{"):
            continue
        verdict = _classify_ai_policy(text)
        if verdict != "unknown":
            return verdict
    return "unknown"


_HOSTILE_PATTERNS = (
    "no ai-generated", "no ai generated", "no llm", "no ai pr",
    "ai-generated prs are not", "do not submit ai", "we do not accept ai",
    "ai-generated contributions are not", "no chatgpt", "no copilot",
    "ai pull requests will be closed", "ai-authored prs",
)
_REQUIRED_PATTERNS = (
    "disclose ai", "disclose llm", "must disclose", "ai disclosure",
    "label ai-generated", "tag ai-generated",
)


def _classify_ai_policy(text: str) -> str:
    """Cheap substring scan. Hostile beats required beats permissive."""
    t = text.lower()
    if any(p in t for p in _HOSTILE_PATTERNS):
        return "hostile"
    if any(p in t for p in _REQUIRED_PATTERNS):
        return "required"
    # Mentions AI policy at all? Treat as permissive (operator complies).
    if "ai" in t and ("policy" in t or "contribution" in t or "guidelin" in t):
        return "permissive"
    return "unknown"


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
