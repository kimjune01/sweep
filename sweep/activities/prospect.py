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
from dataclasses import asdict, dataclass, field
from pathlib import Path

from temporalio import activity
from temporalio.exceptions import ApplicationError

import asyncio

from sweep import gh_io, org_state, seen
from sweep.types import Message


CURSOR_FILE = Path.home() / ".sweep" / "cursors" / "prospect.json"
TRIAGED_INBOX = Path.home() / ".sweep" / "inbox" / "triaged.jsonl"
DEFAULT_CEILING = 10**9   # First lap starts from "any stars."
FLOOR = 100               # Below this, lap is over; next call resets.


# ---------------------------------------------------------------- types


@dataclass
class ProspectRunRequest:
    budget: int = 20            # max repos to scan per pass
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
    CURSOR_FILE.write_text(json.dumps(data, indent=2))


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
    out = subprocess.run(
        [
            "gh", "search", "repos",
            query,
            "--sort", "stars",
            "--order", "desc",
            "--limit", str(limit),
            "--json", "fullName,stargazersCount,openIssuesCount,pushedAt,isArchived,description",
        ],
        capture_output=True, text=True, check=False,
    )
    if out.returncode != 0:
        raise ApplicationError(
            f"gh search repos failed: {out.stderr[:300]}",
            non_retryable=False,
        )
    raw = json.loads(out.stdout or "[]")
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
    """Cheap local checks before any per-repo API call."""
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
    return True


@activity.defn
async def gh_search_actionable_issues(repo: str, limit: int) -> list[IssueCandidate]:
    """Open issues with maintainer-intent labels, no assignee, with no
    PR (any state) referencing them.

    Dedup is a feature of prospecting: never surface an issue that has any
    related PR alive or dead. A live PR means someone's working on it; a
    dead PR (closed/merged) means it's already been addressed or was
    explicitly rejected. Either way, prospect's job is to find work nobody
    has touched.
    """
    if "/" not in repo:
        raise ApplicationError("repo must be owner/repo", non_retryable=True)
    # Single query with OR-d labels — gh's --label flag is AND, so do via search.
    q = (
        f'repo:{repo} is:issue is:open no:assignee '
        f'label:"good first issue","help wanted","bug","enhancement"'
    )
    out = subprocess.run(
        [
            "gh", "search", "issues",
            q,
            "--limit", str(limit),
            "--json", "number,title,url,labels,updatedAt",
        ],
        capture_output=True, text=True, check=False,
    )
    if out.returncode != 0:
        return []
    try:
        raw = json.loads(out.stdout or "[]")
    except json.JSONDecodeError:
        return []

    candidates = [
        IssueCandidate(
            repo=repo,
            number=int(i["number"]),
            title=i.get("title", ""),
            url=i.get("url", ""),
            labels=[l.get("name", "") for l in (i.get("labels") or [])],
            updated_at=i.get("updatedAt", ""),
        )
        for i in raw
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
        events = asyncio.run(gh_io.issue_events(repo, issue_number))
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
    with open(TRIAGED_INBOX, "a") as f:
        f.write(json.dumps(asdict(msg)) + "\n")
    seen.mark_seen(key)
    return msg.msg_id


@activity.defn
async def prospect_one_pass(req: ProspectRunRequest) -> ProspectPassResult:
    """One sweep step. Descend the star cursor by `budget` repos, surface
    actionable issues from the ones that pass lightweight filters."""
    cursor_before = _load_cursor()
    lap_reset = False

    # If cursor has bottomed out, reset to ceiling — next lap.
    if cursor_before <= req.floor:
        cursor_before = DEFAULT_CEILING
        lap_reset = True

    repos = await gh_search_repos_below_stars(
        cursor_before, req.budget, req.languages
    )

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

    return ProspectPassResult(
        repos_visited=len(repos),
        repos_processed=processed,
        issues_found=issues_found,
        delivered_msg_ids=delivered,
        cursor_before=cursor_before,
        cursor_after=cursor_after,
        lap_reset=lap_reset,
    )
