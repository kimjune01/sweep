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
import hashlib
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
    # Recency-first: issues are the origin. Each pass searches
    # GitHub for issues created in the last `days` window, dedupes
    # against the seen set, runs them through the deterministic
    # filters, then through the LLM `should_triage` judge.
    days: int = 30
    # Cap how many issues come back from one search call. The seen
    # set dedupes across calls so re-querying overlapping windows
    # is cheap.
    search_limit: int = 100
    # Per-tick cap on deposits. The puller is demand-driven —
    # it stops firing once triage is full anyway, so this isn't a
    # backpressure mechanism. The real purpose: cap LLM judge calls
    # per pass so one fire doesn't burn through 100 candidates' worth
    # of tokens at once. Sized to triage's queue cap so we can
    # plausibly fill triage in one fire when filters let things through.
    deposit_limit: int = 10


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
    from sweep import budget as _budget
    _budget.set_caller("prospect")
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
        # Side-channel: hostile AI-policy repos are warm targets for the
        # slop-offer pipeline (already publicly committed to the framing).
        # Append-only seed; slop-offer tick consumes. Fail-soft.
        from sweep import slop_offer_seed
        slop_offer_seed.append(repo.name_with_owner)
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
_EVICTED_PATH = Path.home() / ".sweep" / "control" / "prospect_evicted.txt"

# Auto-eviction threshold: this many consecutive losses (closed-unmerged
# OR open-and-hanging-past-TTL) in one repo → evict. Three is the
# Toyota stop-the-line discipline: a defect class repeating that many
# times in one place means the substrate doesn't have leverage there
# (different conventions, different review culture, unfriendly to our
# shape). Stop investing tokens.
EVICTION_LOSS_THRESHOLD = 3
EVICTION_HANGING_DAYS = 30  # open > N days with no merge = counts as a loss


def _on_evicted_list(name_with_owner: str) -> bool:
    """Auto-eviction list (separate from operator-curated kill list).
    Written by `auto_evict_stale_repos`. fnmatch like kill list."""
    if not _EVICTED_PATH.exists():
        return False
    import fnmatch
    name = name_with_owner.lower()
    for raw in _EVICTED_PATH.read_text().splitlines():
        pat = raw.split("#", 1)[0].strip().lower()
        if pat and fnmatch.fnmatch(name, pat):
            return True
    return False


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
    from sweep import budget as _budget
    _budget.set_caller("prospect")
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
    except Exception as e:
        observe.event("issue_events_failed", repo=repo, issue=issue_number,
                      error_type=type(e).__name__, error=str(e)[:200])
        return False  # don't block on transient gh failures
    for ev in events:
        if ev.get("event") == "cross-referenced":
            src = (ev.get("source") or {}).get("issue") or {}
            if src.get("pull_request") is not None:
                return True
    return False


@activity.defn
async def deposit_issue_to_triaged(issue: IssueCandidate,
                                    complexity: str = "unknown") -> str:
    """Append one Message to ~/.sweep/inbox/triaged.jsonl and mark seen.
    `complexity` ∈ {trivial, shallow, medium, deep, unknown} is the
    depth label assigned at prospect time; it propagates downstream so
    every event from triage/investigate/qa/drip can be joined back to
    the original depth probe. Trivial issues should already have been
    filtered out before this call — passing trivial here means the
    operator overrode the filter."""
    key = seen.issue_key(issue.repo, issue.number)
    if seen.has_seen(key):
        return ""  # already delivered in a prior pass
    ts = dt.datetime.now(dt.timezone.utc)
    slug = issue.repo.replace("/", "-")
    # Deterministic id: a retry of this activity (transient I/O on the
    # jsonl write) re-produces the same msg_id, so the actor dedups
    # cleanly. Earlier formulation embedded a call-time minute, so
    # retries crossing a minute boundary created phantom duplicates.
    digest = hashlib.sha256(f"{issue.repo}/{issue.number}".encode()).hexdigest()[:8]
    msg = Message(
        msg_id=f"prospect-{slug}-{issue.number}-{digest}",
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
            "complexity": complexity,
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
    observe.event("prospect_deposited", msg_id=msg.msg_id,
                  repo=issue.repo, issue=issue.number,
                  complexity=complexity)
    # Best-effort signal — same gap as the qa path before: writing
    # jsonl is the view-layer record, but the actor only picks work
    # off its in-memory queue when signaled. Without this, deposits
    # pile up in triaged.jsonl while the actor sits idle. `_signal_actor`
    # emits its own `signal_failed` event on failure; we count strands
    # at deposit time so cockpit can show the gap.
    from sweep.activities.pr_state import _signal_actor
    wf_id = await _signal_actor("triaged", msg)
    if wf_id is None:
        observe.event("deposit_stranded", msg_id=msg.msg_id,
                      repo=issue.repo, issue=issue.number,
                      reason="signal_failed; jsonl written, actor not kicked")
    return msg.msg_id


# Stable system prompt — pulled out of the function so Anthropic's
# prompt cache can fingerprint it. The same bytes every tick → 5-min
# ephemeral cache hit at ~10% cost on the input prefix. With prospect
# ticking on demand-driven cadence, near-every call lands in cache.
# Keep this tight: every token is paid on cache miss (first call,
# post-restart, and post-5-min idle).
_SHOULD_TRIAGE_SYSTEM_TEMPLATE = """\
Rate a GitHub issue for a machine-driven small-PR pipeline.
Output: VERDICT COMPLEXITY (two tokens, uppercase, single space).

Target acceptance rate is ~50% — push toward harder problems where
the substrate has comparative advantage; the goal isn't to ship the
most PRs but to operate at the capability frontier.

VERDICT:
 YES — concrete reproducible failure (test/stack/repro) with WHERE
       hidden; or wide-context coordination, long stack walks,
       polyglot fix, boilerplate-with-invariants at many sites,
       codebase pattern matching. Machines beat humans on specific
       bugs of unknown origin. Minimum complexity: {min_complexity}.
 NO  — UX/aesthetic, design-space, doc taste, refactor without
       failure mode, non-English, one-liner/trivial fix, in-team
       context, ambiguity, any uncertainty, OR complexity below
       {min_complexity}.

COMPLEXITY (machine-leverage depth):
 SHALLOW — single-function bug with clear test.
 MEDIUM  — multi-file, named subsystem invariants, failure
           surface points at where to look.
 DEEP    — long stack across subsystems, race + repro, compiler
           bug with minimal reproducer. Big but structured.
 UNKNOWN — when VERDICT is NO.

If the input is malformed, off-topic, or you cannot evaluate it,
output nothing. Empty is a legal answer; do not fabricate a verdict
you don't believe."""


def _min_complexity() -> str:
    """Current effective difficulty floor. May differ from the target
    floor when auto-loosened by `loosen_floor` to keep the pipe
    flowing. ~/.sweep/control/min_complexity is the effective value;
    ~/.sweep/control/min_complexity_target is the operator's
    preference. Recovery resets effective → target when utilization
    is healthy."""
    path = Path.home() / ".sweep" / "control" / "min_complexity"
    if path.exists():
        v = path.read_text().strip().upper()
        if v in ("SHALLOW", "MEDIUM", "DEEP"):
            return v
    return _target_complexity()


def _target_complexity() -> str:
    """Operator's preferred floor. AIMD recovery snaps effective back
    to this when utilization recovers. Default MEDIUM: the 50%-
    acceptance principle's starting point."""
    path = Path.home() / ".sweep" / "control" / "min_complexity_target"
    if path.exists():
        v = path.read_text().strip().upper()
        if v in ("SHALLOW", "MEDIUM", "DEEP"):
            return v
    return "MEDIUM"


@activity.defn
async def should_triage_issue(issue_payload: dict) -> dict:
    """LLM judge: is this issue worth /triage tokens, and at what depth?

    Output: {"yes": bool, "complexity": str, "reason": str}.
    complexity ∈ {trivial, shallow, medium, deep}. Trivial auto-skips
    upstream; the others are kept and stamped onto the deposit so we
    can probe the pipeline's drowning depth from outcomes.

    Cautious default on `yes` — False on any ambiguity. /triage is the
    next gate and is more expensive; one extra LLM judge here is much
    cheaper than one wasted /triage cycle.
    """
    from sweep import llm_io, models

    system = _SHOULD_TRIAGE_SYSTEM_TEMPLATE.format(min_complexity=_min_complexity())
    body = (issue_payload.get("body") or "")[:1500]
    user = (
        f"Repo: {issue_payload.get('repo', '?')}\n"
        f"Title: {issue_payload.get('title', '?')}\n"
        f"Labels: {', '.join(issue_payload.get('labels', [])) or '(none)'}\n"
        f"Age (hours): {issue_payload.get('age_h', '?')}\n\n"
        f"Body (truncated):\n{body or '(no body)'}\n\n"
        "Output: VERDICT COMPLEXITY"
    )
    try:
        result = await llm_io.call(
            models.default_for("orchestrate"),
            system=system, user=user,
            repo=issue_payload.get("repo", ""),
            pr=issue_payload.get("number"),
            max_tokens=8, temperature=0.0,
            cache_system=True,  # hot path; system bytes stable across ticks
        )
        tokens = (result.response or "").strip().upper().split()
        verdict = tokens[0] if tokens else "NO"
        complexity_raw = tokens[1] if len(tokens) > 1 else "UNKNOWN"
        complexity = complexity_raw.lower()
        if complexity not in ("shallow", "medium", "deep"):
            complexity = "unknown"
        # Enforce the floor server-side too — the prompt may say YES on
        # a SHALLOW when MEDIUM is the floor. The retro_param is the
        # ground truth; the prompt is the LLM's best effort.
        floor_rank = {"SHALLOW": 1, "MEDIUM": 2, "DEEP": 3}
        depth_rank = {"shallow": 1, "medium": 2, "deep": 3, "unknown": 0}
        below_floor = depth_rank[complexity] < floor_rank[_min_complexity()]
        return {
            "yes": verdict.startswith("YES") and not below_floor,
            "complexity": complexity,
            "reason": " ".join(tokens) or "(empty)",
        }
    except Exception as e:
        observe.event("llm_judge_failed", site="should_triage_issue",
                      repo=issue_payload.get("repo", ""),
                      issue=issue_payload.get("number"),
                      error_type=type(e).__name__, error=str(e)[:300])
        return {"yes": False, "complexity": "unknown",
                "reason": f"llm error: {e}"}


@activity.defn
async def prospect_recency_window(req: ProspectRunRequest) -> dict:
    """Recency-first prospect: issues are the origin, repos are
    attributes on issues. The competitive logic: freshly-filed
    actionable issues haven't been seen by other contributors yet.
    Getting in early means no racing PR, no rebase against an
    in-progress fix, maintainer eyes still warm on the bug context.
    First-mover position on the merge race.

    Two-tier funnel (LLM judgment moved to /triage):

      1. Deterministic gates — kill list, star, AI-policy, cheap
         per-issue patterns. All sub-millisecond per check.
      2. Deposit survivors to triaged.jsonl. /triage (per-issue) does
         the LLM judgment as its own decision station, where one-at-a-
         time queueing keeps cost predictable.

    The seen set is the only cursor: each call asks for the last N
    days, dedupes against what we've already processed. Repeating an
    overlapping window costs one gh_search + a set lookup per issue.

    Empty cycles (considered>0 but deposited=0) are expected and not
    a failure mode — they mean the filters did their job and nothing
    in the recent window survived. The puller will keep firing as
    long as triage has slack; the system naturally waits until valid
    work appears, no retry logic needed.
    """
    from sweep import budget as _budget
    _budget.set_caller("prospect")
    if retro_state.is_halted():
        observe.incr("halted_skip:prospect")
        return {"considered": 0, "deposited": 0, "filtered": {}, "halted": True}
    if control_state.is_paused():
        observe.incr("paused_skip:prospect")
        return {"considered": 0, "deposited": 0, "filtered": {}, "paused": True}

    # Cap deposits at whatever triage can currently hold. Demand-pull
    # all the way: prospect only surfaces what downstream can absorb,
    # not a fixed-number-per-tick. Read triage's current depth + cap
    # at the start of each pass.
    from sweep import inbox_state as _inbox
    TRIAGE_CAP = 10  # mirrors cockpit's CAPS["triaged"]["queued"]
    triage_q = len(_inbox.inbox_states("triaged")["queued"])
    free_slots = max(0, TRIAGE_CAP - triage_q)
    effective_cap = min(req.deposit_limit, free_slots)
    if effective_cap <= 0:
        return {"considered": 0, "deposited": 0, "filtered": {"triage_full": 1}}

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=req.days)
    try:
        # Don't pass archived=False — gh CLI returns 0 hits when that
        # flag is combined with --label/--created. The per-issue
        # _passes_deterministic_issue check catches archived repos.
        raw = gh_io.search_issues(
            labels=["bug", "help-wanted"],
            state="open", no_assignee=True, archived=None,
            created_after=cutoff.strftime('%Y-%m-%d'),
            sort="created", order="desc",
            limit=req.search_limit,
        )
    except subprocess.CalledProcessError as e:
        raise ApplicationError(
            f"gh search issues failed: {(e.stderr or '')[:300]}",
            non_retryable=False,
        )

    # Always consider new issues from warm orgs (where we have
    # standing). These get a wider recency window — warmth means
    # the merge race is less brutal, so older issues there are
    # still in play. Merge into the candidate set, dedupe by URL.
    raw = _merge_warm_org_issues(raw, base_cutoff_days=req.days)

    filtered: dict[str, int] = {}
    survivors: list[tuple[int, "IssueCandidate", str, str]] = []  # (rank, ic, complexity, key)
    now = dt.datetime.now(dt.timezone.utc)
    complexity_rank = {"deep": 3, "medium": 2, "shallow": 1, "unknown": 0}

    for it in raw:
        repo_obj = it.get("repository") or {}
        repo = repo_obj.get("nameWithOwner") or repo_obj.get("name_with_owner") or ""
        number = it.get("number")
        if not repo or not number:
            filtered["malformed"] = filtered.get("malformed", 0) + 1
            continue
        key = seen.issue_key(repo, number)
        if seen.has_seen(key):
            filtered["seen"] = filtered.get("seen", 0) + 1
            continue
        # Skip if this issue has a related PR (any state).
        if _has_related_pr(repo, number):
            filtered["has_pr"] = filtered.get("has_pr", 0) + 1
            seen.mark_seen(key)
            continue
        # Tier 1a: cheap per-issue gates — title patterns, body
        # length, comment count, leverage signals. Don't seen-mark
        # on rejection: filter patterns can change (loosened regex,
        # new leverage signals) and a previously-rejected issue
        # should re-evaluate against the current rules.
        cheap_reason = _cheap_issue_skip(it)
        if cheap_reason:
            filtered[f"cheap_{cheap_reason}"] = filtered.get(f"cheap_{cheap_reason}", 0) + 1
            continue
        # Tier 1b: deterministic gates. Same logic — kill list, star
        # gate, AI policy can all change; don't seen-mark on rejection.
        repo_meta = _fetch_repo_meta_cheap(repo)
        if not _passes_deterministic_issue(repo, repo_meta):
            filtered["deterministic"] = filtered.get("deterministic", 0) + 1
            continue
        # Survivor — no LLM call here. The per-issue LLM judgment
        # belongs in /triage (TriageActor's job). Prospect's role is
        # ingest + cheap deterministic filter. Keeping it that way
        # keeps prospect sub-second per fire and pushes LLM cost into
        # a queue where it can be one-at-a-time, not burst per fire.
        labels = [l.get("name", "") for l in it.get("labels") or []]
        ic = IssueCandidate(
            repo=repo, number=int(number),
            title=it.get("title", ""),
            url=it.get("url", ""),
            labels=labels,
            updated_at=it.get("updatedAt", "") or "",
        )
        # No complexity tag at this stage — /triage assigns it via its
        # decision. Default to "unknown" so downstream events can join.
        survivors.append((0, ic, "unknown", key))

    # No deepest-first sort here either (we don't know depth yet).
    # Take in search order (recency for global; sort order from gh
    # for warm-org). /triage will decide and emit complexity.

    deposited = 0
    deposited_ids: list[str] = []
    for _, ic, complexity, _key in survivors[:effective_cap]:
        msg_id = await deposit_issue_to_triaged(ic, complexity=complexity)
        deposited_ids.append(msg_id)
        deposited += 1
    # Any survivors beyond the cap stay unseen so the next pass can
    # re-evaluate and possibly deposit them when there's slack.
    for _, _ic, _c, _key in survivors[effective_cap:]:
        filtered["over_cap"] = filtered.get("over_cap", 0) + 1

    observe.event(
        "prospect_window",
        considered=len(raw), deposited=deposited, filtered=filtered,
        window_days=req.days,
    )
    return {
        "considered": len(raw),
        "deposited": deposited,
        "deposited_msg_ids": deposited_ids,
        "filtered": filtered,
    }


import re

# Title prefixes that signal non-bug work — discussion/RFC/feature
# requests we don't want to spend LLM tokens evaluating. Anchored at
# start (with optional brackets/markers) so we don't false-positive on
# "Fix RFC parser" or similar.
_NON_BUG_TITLE_RE = re.compile(
    r"^(\[?\s*)?(rfc|proposal|feature|discussion|question|idea|enhancement)s?\b",
    re.IGNORECASE,
)

# Cheap leverage signals — presence of any of these in the body
# raises the chance this is a machine-friendly bug. Absence of all
# of them with a short body = probably vague, skip.
_LEVERAGE_SIGNALS = ("```", "Traceback", "Error:", "Exception", "stack trace",
                     "expected", "actual", "reproduce", "repro:", "steps to ",
                     "http://", "https://", "/usr/", "  File \"")


def _cheap_issue_skip(item: dict) -> str | None:
    """Per-issue deterministic skip checks — title patterns, body
    length, conversation depth, leverage proxies. Each rejection here
    saves one paid LLM judge call. Returns a short reason tag for the
    `filtered` dict, or None if the issue should reach the LLM judge.
    """
    title = (item.get("title") or "").strip()
    body = (item.get("body") or "")
    comments = int(item.get("commentsCount") or 0)

    if _NON_BUG_TITLE_RE.match(title):
        return "non_bug_title"
    if len(body) < 100:
        return "thin_body"
    if comments > 20:
        return "saturated_thread"
    # Leverage proxy: a real bug usually has at least one of stack
    # trace / error string / repro fence / URL / file path.
    blower = body.lower()
    if not any(sig.lower() in blower for sig in _LEVERAGE_SIGNALS):
        return "no_leverage_signals"
    return None


def _merge_warm_org_issues(global_results: list[dict], *,
                            base_cutoff_days: int) -> list[dict]:
    """Add warm-org issues to the candidate set, deduped by URL.

    Warm orgs are where the operator has merge history — the standing
    gate doesn't apply, the merge race is less brutal, and the
    maintainer is more likely to engage on a contribution. So we
    always sweep them, with a wider recency window than the global
    search. The global search captures the recency-first / first-mover
    advantage; this captures the standing-leveraged opportunities the
    global search might miss.

    Per-org searches are cached 30min in gh_io, so this costs N gh
    calls per cache window where N = warm-org count.
    """
    warm_cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(
        days=max(90, base_cutoff_days * 3)
    )
    warm_cutoff_iso = warm_cutoff.strftime('%Y-%m-%d')
    try:
        warm_state = warm_orgs.state()
        warm_org_list = list((warm_state.get("orgs") or {}).keys())
    except Exception:
        return global_results
    seen_urls = {(it.get("url") or "") for it in global_results}
    merged = list(global_results)
    for org in warm_org_list:
        if not org:
            continue
        try:
            # No label filter on warm orgs — we have standing here,
            # any open issue is plausibly engageable. The label gate
            # was a cheap proxy for "actionable" against the global
            # firehose; for warm orgs, let the LLM judge sort it out.
            org_results = gh_io.search_issues(
                state="open", no_assignee=True, archived=None,
                created_after=warm_cutoff_iso,
                owner=org,
                sort="created", order="desc",
                limit=30,
            )
        except Exception as e:
            observe.event("warm_org_search_failed", org=org,
                          error_type=type(e).__name__, error=str(e)[:200])
            continue
        for it in org_results:
            url = it.get("url") or ""
            if url and url not in seen_urls:
                seen_urls.add(url)
                merged.append(it)
    return merged


def _fetch_repo_meta_cheap(repo: str) -> dict:
    """{stars, archived, language, pushed_at} for one repo. Cached
    via gh_io's sqlite cache."""
    try:
        return gh_io._cached_json(
            "repo_view_lite",
            ["api", f"repos/{repo}", "--jq",
             "{stars: .stargazers_count, archived: .archived, "
             "language: .language, pushed_at: .pushed_at}"],
            ttl=24 * 3600,
        )
    except Exception as e:
        # Fail closed: archived=True keeps a meta-fetch failure from
        # silently letting an actually-archived repo pass the filter.
        observe.event("repo_meta_fetch_failed", repo=repo,
                      error_type=type(e).__name__, error=str(e)[:200])
        return {"stars": 0, "archived": True, "language": None, "pushed_at": None}


def _passes_deterministic_issue(repo: str, meta: dict) -> bool:
    """Same lattice as `_passes_lightweight_filter`, applied to a
    bare-bones repo dict instead of a RepoCandidate.

    Org-JIT differentiated by warmth: cold orgs still strict
    (1 open PR max, no TTL — don't spam someone we've never
    engaged). Warm orgs get a `WARM_ORG_PR_TTL_DAYS` TTL: PRs older
    than that aren't counted toward the block. The maintainer's
    silence past a week is the signal that they're not actively on
    it; opening another PR there isn't spam, it's filling a slot
    they've effectively vacated.
    """
    if meta.get("archived"):
        return False
    org = org_state.org_of(repo)
    warm = warm_orgs.is_warm(org)
    if warm:
        if _warm_org_blocked(org):
            return False
    else:
        if org_state.is_org_blocked(org):  # cold: cap=1, no TTL
            return False
    if _on_kill_list(repo) or _on_evicted_list(repo):
        return False
    if meta.get("stars", 0) > BIG_REPO_STAR_THRESHOLD and not warm:
        return False
    if gh_io.repo_ai_policy(repo) == "hostile":
        from sweep import slop_offer_seed
        slop_offer_seed.append(repo)
        return False
    return True


WARM_ORG_PR_TTL_DAYS = 7


def _warm_org_blocked(org: str) -> bool:
    """Warm-org block check with a `WARM_ORG_PR_TTL_DAYS` TTL on
    each PR's `created_at`. A PR older than the TTL doesn't count
    toward the block — the maintainer has had a week to engage and
    if they haven't, the slot is effectively vacated. Using created
    (not updated) means CI churn / our own pushes don't keep an old
    PR alive in the JIT's view; only the actual age does."""
    import datetime as _dt
    prs = org_state.state().get("orgs", {}).get(org, [])
    if not prs:
        return False
    cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=WARM_ORG_PR_TTL_DAYS)
    fresh = 0
    for pr in prs:
        # Prefer created_at; fall back to updated_at for old records
        # that org_state cached before we added the field.
        ts = pr.get("created_at") or pr.get("updated_at", "")
        try:
            t = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            fresh += 1  # unknown — count as fresh (conservative)
            continue
        if t >= cutoff:
            fresh += 1
    return fresh >= 1


@activity.defn
async def loosen_floor() -> dict:
    """Drop min_complexity one rung (DEEP → MEDIUM → SHALLOW). Called
    by the puller when too many empty fires accumulate — keeps the
    pipe flowing toward the 20%-utilization floor. Returns the new
    floor and whether it actually changed.

    Only loosens, never tightens — tightening stays operator-owned so
    the 50%-acceptance principle isn't auto-overridden by a tight loop
    that pushes throughput at the cost of merge rate. The operator
    raises the floor; this activity only ever lowers it.
    """
    path = Path.home() / ".sweep" / "control" / "min_complexity"
    current = _min_complexity()
    next_rung = {"DEEP": "MEDIUM", "MEDIUM": "SHALLOW", "SHALLOW": "SHALLOW"}
    new = next_rung[current]
    if new == current:
        return {"floor": current, "changed": False}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new + "\n")
    observe.event("floor_loosened", from_floor=current, to=new,
                  reason="empty_streak_threshold")
    return {"floor": new, "changed": True}


@activity.defn
async def auto_evict_stale_repos() -> dict:
    """Walk recent PR outcomes, group by repo, find repos with
    EVICTION_LOSS_THRESHOLD consecutive losses (closed-unmerged or
    open-but-hanging-past-EVICTION_HANGING_DAYS), append to
    ~/.sweep/control/prospect_evicted.txt. Idempotent — duplicates
    are deduped on read. Returns {evicted_new, evicted_total}.
    """
    import datetime as _dt
    from sweep import outcomes as _oc

    # 90-day lookback should cover any plausible 3-loss streak.
    try:
        oc = _oc.outcomes(days=90)
    except Exception as e:
        return {"evicted_new": 0, "evicted_total": 0, "error": str(e)[:200]}
    merged = oc.get("merged_records", []) or []
    closed = oc.get("closed_records", []) or []

    # Build per-repo timeline of outcomes (newest first). Three
    # outcome kinds count as losses for the 3-in-a-row rule:
    #   • closed     — closed-unmerged in the lookback window
    #   • hanging    — currently open and created > EVICTION_HANGING_DAYS ago
    #                  (30 days open = effectively closed; if the maintainer
    #                   hasn't engaged in a month, they won't)
    # Merges break a streak: a repo with [merged, closed, closed] is not
    # evicted because the merge proves engagement was possible recently.
    timeline: dict[str, list[tuple[str, str]]] = {}  # repo → [(iso, outcome)]
    for r in merged:
        repo = r.get("repo") or r.get("repository", {}).get("nameWithOwner", "")
        if repo:
            timeline.setdefault(repo, []).append((r.get("ts", ""), "merged"))
    for r in closed:
        repo = r.get("repo") or r.get("repository", {}).get("nameWithOwner", "")
        if repo:
            timeline.setdefault(repo, []).append((r.get("ts", ""), "closed"))
    # Hanging open PRs — read from org_state's per-repo records.
    hanging_cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=EVICTION_HANGING_DAYS)
    for org, prs in (org_state.state().get("orgs") or {}).items():
        for pr in prs:
            repo = pr.get("repo", "")
            if not repo:
                continue
            ts = pr.get("created_at") or pr.get("updated_at", "")
            try:
                t = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue
            if t <= hanging_cutoff:
                timeline.setdefault(repo, []).append((ts, "hanging"))

    new_evictions: list[str] = []
    LOSS = ("closed", "hanging")
    for repo, events in timeline.items():
        events.sort(key=lambda x: x[0], reverse=True)  # newest first
        last_n = events[:EVICTION_LOSS_THRESHOLD]
        if (len(last_n) >= EVICTION_LOSS_THRESHOLD
                and all(o in LOSS for _, o in last_n)):
            if not _on_evicted_list(repo):
                new_evictions.append(repo)

    if new_evictions:
        _EVICTED_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _EVICTED_PATH.open("a") as f:
            for repo in new_evictions:
                f.write(f"{repo}  # auto-evicted "
                        f"{_dt.datetime.now(_dt.timezone.utc).isoformat()} "
                        f"({EVICTION_LOSS_THRESHOLD} closed-unmerged in a row)\n")
                observe.event("repo_evicted", repo=repo,
                              reason=f"{EVICTION_LOSS_THRESHOLD}_closed_in_row")

    total = 0
    if _EVICTED_PATH.exists():
        total = sum(1 for ln in _EVICTED_PATH.read_text().splitlines()
                    if ln.strip() and not ln.strip().startswith("#"))
    return {"evicted_new": len(new_evictions), "evicted_total": total,
            "new_repos": new_evictions}


@activity.defn
async def reset_floor() -> dict:
    """AIMD recovery: snap min_complexity back to min_complexity_target.
    Called by the puller when triage utilization is high enough that
    we no longer need the loosened filter to keep work flowing.
    Idempotent — if current already equals target, no-op."""
    path = Path.home() / ".sweep" / "control" / "min_complexity"
    current = _min_complexity()
    target = _target_complexity()
    if current == target:
        return {"floor": current, "changed": False}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(target + "\n")
    observe.event("floor_reset", from_floor=current, to=target,
                  reason="utilization_recovered")
    return {"floor": target, "changed": True}


# Prospect's share of the GitHub core rate limit. Conservative on
# purpose: pr-state polls every open PR on every cycle, drip does
# pushes, qa pulls reviews — they all share the same hourly bucket and
# their loads scale with the number of open PRs, not the operator's
# tempo. 20% leaves ~4000 calls/hr (5000 × 0.80) for everything
# downstream, which is the bottleneck under heavy roster. Bump this
# upward only after rate-limit hits stop appearing in andon.
_API_BUDGET_THRESHOLD = 0.20
# Projected utilization above this means the throttle failed: prospect
# (or something it sits in front of) is burning through the budget
# faster than the 20% cap allows. That's an andon — pull the cord,
# stop the line, demand operator eyes. Block AND record the marker.
_API_BUDGET_ANDON = 0.50
# Hysteresis: don't auto-resume the moment we drop under the andon
# threshold (we'd flap). Recovery happens once projected falls under
# this lower floor. 10-point dead band between andon and recover keeps
# the line from oscillating across the trigger.
_API_BUDGET_RECOVER = 0.40
_API_BUDGET_CACHE_S = 30        # how long to trust a rate_limit snapshot
_api_budget_cache: dict = {"ts": 0.0, "block_reason": None}


def _budget_andon_path():
    from pathlib import Path
    return Path.home() / ".sweep" / "control" / "andon" / "prospect_puller.json"


def _record_budget_andon(reason: str) -> None:
    """Write an andon marker for prospect when the API budget goes
    critical. Inlines the file format from activities.worktree.record_andon
    so we don't need a workflow path to engage the cord."""
    import datetime as _dt
    import json as _json
    from sweep.control_state import set_paused
    path = _budget_andon_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "actor": "prospect_puller",
        "msg_id": "(api budget watchdog)",
        "reason": reason[:500],
        "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }
    path.write_text(_json.dumps(payload))
    set_paused(True)


def _clear_budget_andon_if_held() -> bool:
    """Auto-recover: if our budget-watchdog marker is the one holding
    the line, remove it and lift the pause (when no other markers
    remain). Returns True if a clear happened. Only touches our own
    marker — never clears anyone else's andon."""
    from pathlib import Path
    from sweep.control_state import set_paused
    path = _budget_andon_path()
    if not path.exists():
        return False
    path.unlink()
    andon_dir = Path.home() / ".sweep" / "control" / "andon"
    if not any(andon_dir.glob("*.json")):
        set_paused(False)
    return True


def _api_budget_block() -> str | None:
    """Return a block reason if projected core utilization at reset is
    over prospect's allotted share, else None. Cached for
    `_API_BUDGET_CACHE_S` to keep poll cycles cheap. The `gh api
    rate_limit` call itself doesn't count against the limit (per
    GitHub docs), so polling it is free.

    Cursor-safe: a `False` from this function makes the puller idle
    without invoking `prospect_one_pass`, so the stars cursor stays put."""
    import json as _json
    import subprocess as _sp
    import time as _time

    now = _time.time()
    if now - _api_budget_cache["ts"] < _API_BUDGET_CACHE_S:
        return _api_budget_cache["block_reason"]

    reason: str | None = None
    try:
        raw = _sp.run(
            ["gh", "api", "rate_limit"],
            capture_output=True, text=True, timeout=3,
        )
        if raw.returncode == 0:
            core = _json.loads(raw.stdout).get("resources", {}).get("core", {})
            used = core.get("used", 0)
            limit = core.get("limit", 0)
            reset = core.get("reset", 0)
            if limit:
                secs_remaining = max(1, int(reset - now))
                elapsed = 3600 - secs_remaining
                # Need at least 60s of history before extrapolating —
                # otherwise a single early request looks catastrophic.
                if elapsed >= 60:
                    projected = used * 3600 / elapsed
                    proj_pct = projected / limit
                    # Auto-clear runs FIRST so it can fire even while
                    # the throttle block is still engaged (the throttle
                    # band 20-40% needs to be able to release a prior
                    # andon — otherwise we'd be latched until we drop
                    # under 20%, defeating the hysteresis).
                    if proj_pct < _API_BUDGET_RECOVER:
                        _clear_budget_andon_if_held()
                    if proj_pct >= _API_BUDGET_ANDON:
                        reason = (f"api budget CRITICAL "
                                  f"({100 * proj_pct:.0f}% projected ≥ "
                                  f"{int(_API_BUDGET_ANDON * 100)}% andon threshold)")
                        _record_budget_andon(reason)
                    elif proj_pct >= _API_BUDGET_THRESHOLD:
                        reason = (f"api budget tight "
                                  f"({100 * proj_pct:.0f}% projected, "
                                  f"prospect capped at {int(_API_BUDGET_THRESHOLD * 100)}%)")
    except Exception:
        pass

    _api_budget_cache["ts"] = now
    _api_budget_cache["block_reason"] = reason
    return reason


@activity.defn
async def check_pull_conditions() -> dict:
    """Snapshot of every gate ProspectPuller respects. Returns
    `{can_pull: bool, reason: str, depths: {...}}`. Cheap — pure
    filesystem reads plus a cached rate-limit peek."""
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
    budget_reason = _api_budget_block()
    if budget_reason:
        return {"can_pull": False, "reason": budget_reason, "depths": depths}
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
