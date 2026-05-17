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
Easy to ask "how many gh calls did this sift run actually fire" by
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
    """Fresh hit only — returns None if the row exists but expired.
    Use _cache_get_any to read stale rows for stale-while-revalidate."""
    now = _now().isoformat()
    with _conn() as conn:
        row = conn.execute(
            "SELECT response FROM gh_cache WHERE key = ? AND expires_at > ?",
            (key, now),
        ).fetchone()
    return row[0] if row else None


def _cache_get_any(key: str) -> tuple[str | None, bool]:
    """Returns (response, fresh) for any cached row regardless of TTL.
    Lets readers serve stale data instantly while a background warmer
    refreshes. (None, False) means no row at all — caller must fetch
    synchronously."""
    now = _now().isoformat()
    with _conn() as conn:
        row = conn.execute(
            "SELECT response, expires_at FROM gh_cache WHERE key = ?",
            (key,),
        ).fetchone()
    if not row:
        return None, False
    return row[0], row[1] > now


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
    """Run `gh ARGS`, return stdout. Non-zero exit raises subprocess.CalledProcessError.

    Every successful call charges 1 against the current caller's budget
    (see sweep.budget). Callers tag themselves via `budget.as_caller(...)`
    at activity entry so the per-actor share accounting works. Calls
    that escape attribution land in the 'unknown' bucket — leakdog
    surfaces that gap."""
    out = subprocess.run(["gh"] + args, capture_output=True, text=True, check=False)
    if out.returncode != 0:
        raise subprocess.CalledProcessError(
            out.returncode, ["gh"] + args, output=out.stdout, stderr=out.stderr,
        )
    # Local import — budget imports nothing from gh_io, so no cycle.
    from sweep import budget as _budget
    _budget.record(1)
    return out.stdout


def _cached_json(endpoint: str, args: list[str], ttl: int) -> list | dict:
    """Stale-while-revalidate. Hot path NEVER blocks if the cache has
    ever seen this key:

      - Fresh hit: return cached.
      - Stale hit (TTL expired but row exists): return cached AND kick
        a detached background subprocess to refetch. Next call sees
        fresh data.
      - No row at all (first-ever call): blocking fetch + cache.

    If callers want strict freshness they can clear the row first.
    Stale data is fine when the cache is hit often enough that the
    background refresh catches up before the staleness matters —
    operator displays cycle every few seconds, the warmer takes
    one gh call (~1s)."""
    from sweep import observe  # local import — observe imports nothing from gh_io

    key = _key(endpoint, args)
    raw_cached, fresh = _cache_get_any(key)
    if raw_cached is not None:
        try:
            parsed = json.loads(raw_cached)
        except json.JSONDecodeError:
            parsed = None
        if parsed is not None:
            observe.incr(f"gh_hit:{endpoint}" if fresh else f"gh_stale:{endpoint}")
            if not fresh:
                _spawn_warmer(endpoint, args, ttl, key)
            return parsed

    observe.incr(f"gh_miss:{endpoint}")
    raw = _gh(args)
    try:
        parsed = json.loads(raw) if raw.strip() else []
    except json.JSONDecodeError:
        parsed = []
    _cache_put(key, endpoint, args, json.dumps(parsed), ttl)
    return parsed


def _spawn_warmer(endpoint: str, args: list[str], ttl: int, key: str) -> None:
    """Fire-and-forget background refresh. Lockfile-gated per cache
    key so multiple stale reads in quick succession don't fan out."""
    import sys
    lock_dir = DB_PATH.parent / "warmers"
    lock = lock_dir / f"{key}.lock"
    if lock.exists():
        try:
            if _now().timestamp() - lock.stat().st_mtime < 300:
                return
        except OSError:
            pass
    try:
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock.touch()
    except OSError:
        pass
    try:
        subprocess.Popen(
            [sys.executable, "-m", "sweep.gh_io", "warm",
             endpoint, str(ttl), json.dumps(args)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, start_new_session=True,
        )
    except OSError:
        try:
            lock.unlink()
        except OSError:
            pass


def _warm(endpoint: str, args: list[str], ttl: int) -> None:
    """Synchronous fetch used by the background warmer subprocess.
    Writes the cache row and exits."""
    key = _key(endpoint, args)
    try:
        raw = _gh(args)
        try:
            parsed = json.loads(raw) if raw.strip() else []
        except json.JSONDecodeError:
            parsed = []
        _cache_put(key, endpoint, args, json.dumps(parsed), ttl)
    finally:
        lock = DB_PATH.parent / "warmers" / f"{key}.lock"
        try:
            lock.unlink()
        except OSError:
            pass


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
                  extra_qualifiers: list[str] | None = None,
                  sort: str = "updated", order: str = "desc",
                  limit: int = 100, ttl: int = 1800) -> list[dict]:
    """`gh search issues` wrapper, JSON-shaped. gh refuses inline
    qualifiers like `label:bug` in the positional query — those have
    to be passed as flags (--label bug). Build the arg list flag-form.

    `extra_qualifiers` (e.g. ['-linked:pr']) are raw GitHub search
    qualifiers without a gh CLI flag equivalent. They go after `--` so
    gh stops parsing them as flags and passes them through to the API."""
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
    if extra_qualifiers:
        # `--` separator so gh doesn't try to parse e.g. "-linked:pr"
        # as a flag (`-l` shorthand). Positional args after `--` flow
        # straight into the search query GitHub receives.
        args += ["--", *extra_qualifiers]
    result = _cached_json("search_issues", args, ttl)
    return result if isinstance(result, list) else []


def pr_view(repo: str, pr: int, *,
             fields: str | None = None, ttl: int = 600) -> dict:
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
    'is this human-bucket' classifier since they're often the substantive
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

    Cached aggressively (24h default) because policies don't change daily.
    The verdict itself is what we cache (a short string), not the raw
    file contents — so this path uses _cache_get/_cache_put directly
    rather than _cached_json. Cache key includes the repo only; if any
    of AGENTS.md/CONTRIBUTING.md changes, the verdict re-derives on
    the next miss after expiry.
    """
    if "/" not in repo:
        return "unknown"
    cache_key = _key("repo_ai_policy", [repo])
    hit = _cache_get(cache_key)
    if hit is not None:
        from sweep import observe
        observe.incr("gh_hit:repo_ai_policy")
        return hit
    from sweep import observe
    observe.incr("gh_miss:repo_ai_policy")
    # AGENTS.md first (the emerging convention), then CONTRIBUTING.md.
    verdict = "unknown"
    for path in ("AGENTS.md", "CONTRIBUTING.md", "CONTRIBUTING.rst"):
        try:
            text = _gh(["api", f"repos/{repo}/contents/{path}",
                        "-H", "Accept: application/vnd.github.raw"])
        except subprocess.CalledProcessError:
            continue
        if not text or text.startswith("{"):
            continue
        v = _classify_ai_policy(text)
        if v != "unknown":
            verdict = v
            break
    _cache_put(cache_key, "repo_ai_policy", [repo], verdict, ttl)
    return verdict


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


if __name__ == "__main__":
    # Background warmer entrypoint:
    #   python -m sweep.gh_io warm <endpoint> <ttl> <json_args>
    import sys
    if len(sys.argv) >= 5 and sys.argv[1] == "warm":
        endpoint = sys.argv[2]
        ttl = int(sys.argv[3])
        args = json.loads(sys.argv[4])
        _warm(endpoint, args, ttl)
