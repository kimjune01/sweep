"""Prospect — windshield-wiper sweep through GitHub repos by descending stars.

The cursor moves at whatever rate it moves. Each `prospect_one_pass` invocation
walks a budget-bounded chunk of repos below the current star cursor, filters
out the ones that don't pass auxiliary checks, scrapes actionable issues from
the remaining repos, dedupes against ~/.sweep/seen/issues.txt, and deposits
the survivors into ~/.sweep/inbox/triaged.jsonl for /triage to score.

Star order is just the sweep dimension — not a value ranking. Auxiliary
filters decide what actually gets processed. Skipped repos don't stall the
cursor; it walks past them.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import urllib.parse
from dataclasses import asdict, dataclass, field
from pathlib import Path

from temporalio import activity
from temporalio.exceptions import ApplicationError

from sweep import control_state, gh_io, observe, org_state, retro_state, seen, warm_orgs
from sweep.io_safe import atomic_write_text
from sweep.types import Message


CURSOR_FILE = Path.home() / ".sweep" / "cursors" / "prospect.json"
TRIAGED_INBOX = Path.home() / ".sweep" / "inbox" / "triaged.jsonl"
DEFAULT_CEILING = 10**9   # First lap starts from "any stars."
FLOOR = 100               # Below this, lap is over; next call resets.


# ---------------------------------------------------------------- types


@dataclass
class ProspectRunRequest:
    # Default 1 = Toyota-style one-piece flow. Each pass scans one
    # repo, surfaces its issues, hands off to triage, returns. The
    # ticker fires fast (every few min) instead of slow (every hour),
    # so total throughput stays similar but arrivals smooth out and
    # backpressure response is per-repo, not per-batch.
    budget: int = 1
    floor: int = FLOOR          # star floor (lap reset trigger)
    issue_limit_per_repo: int = 5
    languages: list[str] = field(default_factory=list)  # optional language filter


@dataclass
class RepoCandidate:
    name_with_owner: str        # "owner/repo"
    stars: int
    open_issues: int
    pushed_at: str
    is_archived: bool
    description: str = ""


@dataclass
class IssueCandidate:
    repo: str
    number: int
    title: str
    url: str
    labels: list[str]
    updated_at: str


@dataclass
class ProspectPassResult:
    repos_visited: int
    repos_processed: int
    issues_found: int
    delivered_msg_ids: list[str]
    cursor_before: int
    cursor_after: int
    lap_reset: bool = False


# ---------------------------------------------------------------- cursor


def _load_cursor() -> int:
    if not CURSOR_FILE.exists():
        return DEFAULT_CEILING
    try:
        data = json.loads(CURSOR_FILE.read_text())
        return int(data.get("stars_cursor", DEFAULT_CEILING))
    except (json.JSONDecodeError, OSError, ValueError):
        return DEFAULT_CEILING


def _save_cursor(stars: int, *, lap_reset: bool = False) -> None:
    CURSOR_FILE.parent.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    prior = {}
    if CURSOR_FILE.exists():
        try:
            prior = json.loads(CURSOR_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    data = {
        "stars_cursor": int(stars),
        "started_at": prior.get("started_at") or now,
        "last_run_at": now,
        "last_lap_reset_at": now if lap_reset else prior.get("last_lap_reset_at"),
    }
    # Atomic — a crash mid-write would otherwise leave a truncated/empty
    # cursor that _load_cursor reads as DEFAULT_CEILING, forcing a full
    # lap reset. Same reason observe.cursor_set went through atomic_write.
    atomic_write_text(CURSOR_FILE, json.dumps(data, indent=2))


# ---------------------------------------------------------------- activities


@activity.defn
async def gh_search_repos_below_stars(stars_ceiling: int, limit: int,
                                       languages: list[str]) -> list[RepoCandidate]:
    """Fetch the next `limit` repos with stars < ceiling, descending stars."""
    if stars_ceiling <= 0:
        return []
    q_parts = [f"stars:<{stars_ceiling}", "is:public", "archived:false"]
    for lang in languages:
        q_parts.append(f"language:{lang}")
    query = " ".join(q_parts)
    try:
        raw = gh_io.search_repos(
            query,
            sort="stars",
            order="desc",
            limit=limit,
            fields="fullName,stargazersCount,openIssuesCount,pushedAt,isArchived,description",
            ttl=600,
        )
    except subprocess.CalledProcessError as e:
        raise ApplicationError(
            f"gh search repos failed: {(e.stderr or '')[:300]}",
            non_retryable=False,
        )
    return [
        RepoCandidate(
            name_with_owner=r["fullName"],
            stars=r.get("stargazersCount", 0),
            open_issues=r.get("openIssuesCount", 0),
            pushed_at=r.get("pushedAt", ""),
            is_archived=bool(r.get("isArchived")),
            description=r.get("description") or "",
        )
        for r in raw
    ]


def _passes_lightweight_filter(repo: RepoCandidate) -> bool:
    """Cheap local checks before any per-repo API call.

    The lessons from HYPOTHESIS_GRAPH.md encoded as rejections:
      • H13 — explicit kill list for GUI/TUI / AI-hostile / known-bad repos
        (jellyfin-tui cascade, ytmusic-deleter, immich, etc.)
      • H2a — big repos (>5k stars) gate contributors on standing; if we
        have no warmth in the org, our PRs die in review. Skip them at
        prospect time instead of paying triage tokens to discover that.
    """
    if repo.is_archived:
        return False
    if repo.open_issues <= 0:
        return False
    # Pushed within 180 days = some sign of life.
    if repo.pushed_at:
        try:
            t = dt.datetime.fromisoformat(repo.pushed_at.replace("Z", "+00:00"))
            if (dt.datetime.now(dt.timezone.utc) - t).days > 180:
                return False
        except (ValueError, AttributeError):
            pass
    # Org-state gate: don't surface issues for orgs that already have
    # one of our PRs open. Reviews are org-gated; adding more work to a
    # blocked org wastes tokens and risks the maintainer-spam tax.
    org = org_state.org_of(repo.name_with_owner)
    if org_state.is_org_blocked(org):
        return False
    # H13 kill list — operator-curated patterns, hot-reloadable.
    if _on_kill_list(repo.name_with_owner):
        return False
    # H2a standing gate — big cold-org repos need standing we don't have.
    if repo.stars > BIG_REPO_STAR_THRESHOLD and not warm_orgs.is_warm(org):
        return False
    # AGENTS.md / CONTRIBUTING AI-policy probe — only "hostile" filters;
    # "required" / "permissive" / "unknown" all pass. Result is cached
    # 24h in gh_io so this is one API call per repo per day.
    if gh_io.repo_ai_policy(repo.name_with_owner) == "hostile":
        return False
    return True


# Standing gate: above this star count + not warm = "they screen
# contributors before reading code." Inferred from HYPOTHESIS_GRAPH H2a
# (pallets / tinygrad / Enzyme pattern). Configurable downstream by
# adjusting warm_orgs's min_merged param to expand the warmth definition.
# Raised 5k → 10k as standing accumulates and the operator can take on
# higher-visibility orgs cold without immediately dying in review.
BIG_REPO_STAR_THRESHOLD = 10000


_KILL_LIST_PATH = Path.home() / ".sweep" / "control" / "prospect_kill_list.txt"


def _on_kill_list(name_with_owner: str) -> bool:
    """fnmatch-style patterns, one per line, comments with '#'. Re-read
    each call — small file, hot-reloadable without restart. Operator
    edits and the next prospect tick picks it up.
    """
    if not _KILL_LIST_PATH.exists():
        return False
    import fnmatch
    name = name_with_owner.lower()
    for raw in _KILL_LIST_PATH.read_text().splitlines():
        pat = raw.split("#", 1)[0].strip().lower()
        if not pat:
            continue
        if fnmatch.fnmatch(name, pat):
            return True
    return False


def _warm_first(repos: list[RepoCandidate]) -> list[RepoCandidate]:
    """Stable partition: warm-org repos first, cold after. Star order is
    preserved within each bucket."""
    warm, cold = [], []
    for r in repos:
        org = org_state.org_of(r.name_with_owner)
        (warm if warm_orgs.is_warm(org) else cold).append(r)
    return warm + cold


ACTIONABLE_LABELS = ("good first issue", "help wanted", "bug", "enhancement")


@activity.defn
async def gh_search_actionable_issues(repo: str, limit: int) -> list[IssueCandidate]:
    """Open issues with maintainer-intent labels, no assignee, with no
    PR (any state) referencing them.

    Dedup is a feature of prospecting: never surface an issue that has any
    related PR alive or dead. A live PR means someone's working on it; a
    dead PR (closed/merged) means it's already been addressed or was
    explicitly rejected. Either way, prospect's job is to find work nobody
    has touched.

    Why we hit /search/issues directly instead of `gh search issues`:
    the multi-word OR'd labels qualifier — label:"good first issue",
    "help wanted" — does not survive the gh CLI's argv handling. shlex
    strips the inner quotes and a single-arg passthrough makes gh wrap
    the whole thing in extra quotes. Either way, the GitHub API receives
    a malformed qualifier and matches zero issues. Posting through
    `gh api /search/issues?q=...` with a URL-encoded query gives us
    direct control over the quoting that reaches the search backend.
    """
    if "/" not in repo:
        raise ApplicationError("repo must be owner/repo", non_retryable=True)

    label_clause = ",".join(f'"{l}"' for l in ACTIONABLE_LABELS)
    qual = (
        f"repo:{repo} is:issue is:open no:assignee "
        f"label:{label_clause}"
    )
    path = (
        f"/search/issues?q={urllib.parse.quote(qual)}"
        f"&per_page={limit}"
    )
    try:
        resp = gh_io.api(path, ttl=120)
    except subprocess.CalledProcessError:
        return []
    items = resp.get("items", []) if isinstance(resp, dict) else []

    # /search/issues uses snake_case (html_url, updated_at) where the gh
    # CLI projects camelCase. Map both to our internal shape.
    candidates = [
        IssueCandidate(
            repo=repo,
            number=int(i["number"]),
            title=i.get("title", ""),
            url=i.get("html_url") or i.get("url", ""),
            labels=[l.get("name", "") for l in (i.get("labels") or [])],
            updated_at=i.get("updated_at") or i.get("updatedAt", ""),
        )
        for i in items
        if "number" in i
    ]
    # Dedup against any PR referencing the issue, alive or dead.
    return [c for c in candidates if not _has_related_pr(repo, c.number)]


def _has_related_pr(repo: str, issue_number: int) -> bool:
    """True if any PR in `repo` (any state) references issue #N.

    Uses gh_io.issue_events — cross-reference events from PRs show up
    regardless of PR state. Cached with 5-min TTL so repeated sweeps in
    the same session don't re-fetch.
    """
    try:
        events = gh_io.issue_events(repo, issue_number)
    except Exception:
        return False  # don't block on transient gh failures
    for ev in events:
        if ev.get("event") == "cross-referenced":
            src = (ev.get("source") or {}).get("issue") or {}
            if src.get("pull_request") is not None:
                return True
    return False


@activity.defn
async def deposit_issue_to_triaged(issue: IssueCandidate) -> str:
    """Append one Message to ~/.sweep/inbox/triaged.jsonl and mark seen.
    Returns the msg_id."""
    key = seen.issue_key(issue.repo, issue.number)
    if seen.has_seen(key):
        return ""  # already delivered in a prior pass
    ts = dt.datetime.now(dt.timezone.utc)
    ts_minute = ts.strftime("%Y-%m-%dT%H:%MZ")
    slug = issue.repo.replace("/", "-")
    msg = Message(
        msg_id=f"prospect-{ts_minute}-{slug}-{issue.number}",
        sender="prospect",
        intent="investigate",
        repo=issue.repo,
        pr=issue.number,
        branch=None,
        payload={
            "title": issue.title,
            "url": issue.url,
            "labels": issue.labels,
            "updated_at": issue.updated_at,
            "kind": "issue",
        },
        ts=ts.isoformat(),
    )
    TRIAGED_INBOX.parent.mkdir(parents=True, exist_ok=True)
    if control_state.is_dry():
        dry_path = TRIAGED_INBOX.parent / "triaged.dry.jsonl"
        with open(dry_path, "a") as f:
            f.write(json.dumps(asdict(msg)) + "\n")
        observe.event("dry_skip", site="prospect_deliver",
                      actor="triaged", msg_id=msg.msg_id,
                      repo=issue.repo, pr=issue.number)
        # Don't mark_seen under dry — the operator should be able to clear
        # the flag and have the same issues re-deliver to the live inbox.
        return msg.msg_id
    with open(TRIAGED_INBOX, "a") as f:
        f.write(json.dumps(asdict(msg)) + "\n")
    seen.mark_seen(key)
    return msg.msg_id


@activity.defn
async def check_pull_conditions() -> dict:
    """Snapshot of every gate ProspectPuller respects. Returns
    `{can_pull: bool, reason: str, depths: {...}}`. Cheap — pure
    filesystem reads, no GitHub calls."""
    from sweep import inbox_state as _inbox

    paused = control_state.is_paused()
    halted = retro_state.is_halted()
    states = {a: _inbox.inbox_states(a) for a in ("triaged", "investigate")}
    depths = {a: len(s["queued"]) for a, s in states.items()}
    # Caps lifted from cockpit.py; importing the dict directly would
    # cycle, so we inline. Bump here if cockpit's CAPS change.
    caps = {"triaged": 10, "investigate": 5}

    if paused:
        return {"can_pull": False, "reason": "paused", "depths": depths}
    if halted:
        return {"can_pull": False, "reason": "retro halted", "depths": depths}
    if depths["triaged"] >= caps["triaged"]:
        return {"can_pull": False,
                "reason": f"triage full ({depths['triaged']}/{caps['triaged']})",
                "depths": depths}
    if depths["investigate"] >= caps["investigate"]:
        return {"can_pull": False,
                "reason": f"investigate full ({depths['investigate']}/{caps['investigate']})",
                "depths": depths}
    return {"can_pull": True, "reason": "ready", "depths": depths}


@activity.defn
async def prospect_one_pass(req: ProspectRunRequest) -> ProspectPassResult:
    """One sweep step. Descend the star cursor by `budget` repos, surface
    actionable issues from the ones that pass lightweight filters."""
    if retro_state.is_halted():
        # Backpressure from the retro pager. Forward pass stops until the
        # human Attends to at least one of the pending SOAP one-pagers.
        observe.incr("halted_skip:prospect")
        return ProspectPassResult(
            repos_visited=0, repos_processed=0, issues_found=0,
            delivered_msg_ids=[],
            cursor_before=_load_cursor(), cursor_after=_load_cursor(),
            lap_reset=False,
        )
    if control_state.is_paused():
        # Operator-initiated soft-pause. Same no-op shape as the retro
        # halt — in-flight work elsewhere keeps running.
        observe.incr("paused_skip:prospect")
        return ProspectPassResult(
            repos_visited=0, repos_processed=0, issues_found=0,
            delivered_msg_ids=[],
            cursor_before=_load_cursor(), cursor_after=_load_cursor(),
            lap_reset=False,
        )
    cursor_before = _load_cursor()
    lap_reset = False

    # If cursor has bottomed out, reset to ceiling — next lap.
    if cursor_before <= req.floor:
        cursor_before = DEFAULT_CEILING
        lap_reset = True

    repos = await gh_search_repos_below_stars(
        cursor_before, req.budget, req.languages
    )

    repos = _warm_first(repos)

    processed = 0
    issues_found = 0
    delivered: list[str] = []
    lowest_stars = cursor_before

    for repo in repos:
        # Cursor advances on every repo, processed or not.
        lowest_stars = min(lowest_stars, repo.stars)
        if not _passes_lightweight_filter(repo):
            continue
        issues = await gh_search_actionable_issues(
            repo.name_with_owner, req.issue_limit_per_repo
        )
        if not issues:
            continue
        processed += 1
        for issue in issues:
            mid = await deposit_issue_to_triaged(issue)
            if mid:
                delivered.append(mid)
                issues_found += 1

    cursor_after = lowest_stars if repos else cursor_before
    _save_cursor(cursor_after, lap_reset=lap_reset)

    observe.incr("prospect_repos_visited", len(repos))
    observe.incr("prospect_repos_processed", processed)
    observe.incr("prospect_issues_found", issues_found)
    if lap_reset:
        observe.incr("prospect_lap_reset")
    observe.event(
        "prospect_pass",
        cursor_before=cursor_before,
        cursor_after=cursor_after,
        repos_visited=len(repos),
        repos_processed=processed,
        issues_found=issues_found,
        lap_reset=lap_reset,
    )

    return ProspectPassResult(
        repos_visited=len(repos),
        repos_processed=processed,
        issues_found=issues_found,
        delivered_msg_ids=delivered,
        cursor_before=cursor_before,
        cursor_after=cursor_after,
        lap_reset=lap_reset,
    )
