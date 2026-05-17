"""Sift — per-issue screen. The live actor is `sift_cycle` (one
card = one issue, filter inline, ≤1 fresh gh call). This module also
still hosts the legacy star-cursor `sift_one_pass` path used by
`sweep sift run` as an escape hatch. Cursor doc below describes that
legacy path.

The star cursor moves at whatever rate it moves. Each `sift_one_pass` invocation
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


CURSOR_FILE = Path.home() / ".sweep" / "cursors" / "sift_legacy.json"
TRIAGED_INBOX = Path.home() / ".sweep" / "inbox" / "triaged.jsonl"
DEFAULT_CEILING = 10**9   # First lap starts from "any stars."
FLOOR = 100               # Below this, lap is over; next call resets.


# ---------------------------------------------------------------- types


@dataclass
class SiftRunRequest:
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
class SiftPassResult:
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
    _budget.set_caller("sift")
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
        sift time instead of paying triage tokens to discover that.
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
        # Hostile repos route to the immunize actor — immunize decides
        # whether they're worth pursuing via slop-offer (visibility,
        # recency, dedupe) instead of every sift tick auto-seeding.
        # Fail-soft: signaling failures emit observe events but never
        # raise — sift's hot path stays liveness-preserving.
        try:
            import asyncio as _asyncio
            from sweep.activities.immunize import kick_immunize_card
            _asyncio.create_task(kick_immunize_card(
                repo.name_with_owner, None, source="sift-lightweight",
            ))
        except Exception:
            pass
        return False
    return True


# Standing gate: above this star count + not warm = "they screen
# contributors before reading code." Inferred from HYPOTHESIS_GRAPH H2a
# (pallets / tinygrad / Enzyme pattern). Configurable downstream by
# adjusting warm_orgs's min_merged param to expand the warmth definition.
# Raised 5k → 10k as standing accumulates and the operator can take on
# higher-visibility orgs cold without immediately dying in review.
BIG_REPO_STAR_THRESHOLD = 10000


_KILL_LIST_PATH = Path.home() / ".sweep" / "control" / "sift_kill_list.txt"
_EVICTED_PATH = Path.home() / ".sweep" / "control" / "sift_evicted.txt"

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
    edits and the next sift tick picks it up.
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

    Dedup is a feature of sifting: never surface an issue that has any
    related PR alive or dead. A live PR means someone's working on it; a
    dead PR (closed/merged) means it's already been addressed or was
    explicitly rejected. Either way, sift's job is to find work nobody
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
    _budget.set_caller("sift")
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
    depth label assigned at sift time; it propagates downstream so
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
        msg_id=f"sift-{slug}-{issue.number}-{digest}",
        sender="sift",
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
        observe.event("dry_skip", site="sift_deliver",
                      actor="triaged", msg_id=msg.msg_id,
                      repo=issue.repo, pr=issue.number)
        # Don't mark_seen under dry — the operator should be able to clear
        # the flag and have the same issues re-deliver to the live inbox.
        return msg.msg_id
    with open(TRIAGED_INBOX, "a") as f:
        f.write(json.dumps(asdict(msg)) + "\n")
    seen.mark_seen(key)
    observe.event("sift_deposited", msg_id=msg.msg_id,
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
# ephemeral cache hit at ~10% cost on the input prefix. With sift
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


# --- sift cost knobs (operator-tunable from ~/.sweep/control/) ----
# Same hot-reload pattern as _min_complexity: read each call, no cache.
# Files are plaintext ints; missing/malformed = use the default.

PROSPECT_SEARCH_LIMIT_DEFAULT = 100
PROSPECT_WARM_ORG_FAN_OUT_CAP_DEFAULT = 3
PROSPECT_WARM_ORG_ISSUE_LIMIT_DEFAULT = 30
PROSPECT_MIN_ISSUE_AGE_MINUTES_DEFAULT = 3


def _read_int_knob(name: str, default: int, *, lo: int = 1, hi: int = 1000) -> int:
    path = Path.home() / ".sweep" / "control" / name
    if not path.exists():
        return default
    try:
        v = int(path.read_text().strip())
    except (OSError, ValueError):
        return default
    return max(lo, min(hi, v))


def _search_limit() -> int:
    """Cap on issues returned per pass from the global gh_search. Each
    survivor costs one `issue_events` call downstream — this is the
    biggest single lever on sift's hourly gh budget."""
    return _read_int_knob("sift_search_limit",
                          PROSPECT_SEARCH_LIMIT_DEFAULT)


def _warm_org_fan_out_cap() -> int:
    """Max warm orgs visited per pass. With the cap, _merge_warm_org_issues
    round-robins via the cursor below so coverage amortizes across passes."""
    return _read_int_knob("sift_warm_org_fan_out_cap",
                          PROSPECT_WARM_ORG_FAN_OUT_CAP_DEFAULT, hi=100)


def _warm_org_issue_limit() -> int:
    """Per-warm-org issue cap inside _merge_warm_org_issues."""
    return _read_int_knob("sift_warm_org_issue_limit",
                          PROSPECT_WARM_ORG_ISSUE_LIMIT_DEFAULT, hi=200)


def _min_issue_age_minutes() -> int:
    """Minimum age (in minutes) before an issue is considered for
    triage. The maintainer-self-PR pattern (open issue then immediately
    open the PR yourself) shows up as a rejection at /investigate, after
    we've already spent triage tokens. Filtering at sift time on a
    short delay catches most of these for one cheap timestamp check.
    Cedes a small first-mover advantage on issues no maintainer will
    engage with, which is acceptable because that's not our edge anyway."""
    return _read_int_knob("sift_min_issue_age_minutes",
                          PROSPECT_MIN_ISSUE_AGE_MINUTES_DEFAULT, hi=120)




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
        # Route to immunize (the worth-pursuing decider for slop-offer
        # candidates). Fire-and-forget — running inside an async caller
        # so the loop is available; failures are observable via events.
        try:
            import asyncio as _asyncio
            from sweep.activities.immunize import kick_immunize_card
            _asyncio.create_task(kick_immunize_card(
                repo, None, source="sift-deterministic",
            ))
        except Exception:
            pass
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
    ~/.sweep/control/sift_evicted.txt. Idempotent — duplicates
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





_SIFT_STATE_PATH = Path.home() / ".sweep" / "state" / "sift_actor.json"
PROSPECT_EVICT_EVERY = 10  # auto_evict_stale_repos runs every Nth cycle
PROSPECT_LOOSEN_EMPTY_STREAK = 5  # loosen the floor after N empties in a row


def _load_sift_state() -> dict:
    if not _SIFT_STATE_PATH.exists():
        return {"empty_streak": 0, "fires_total": 0}
    try:
        return json.loads(_SIFT_STATE_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {"empty_streak": 0, "fires_total": 0}


def _save_sift_state(state: dict) -> None:
    try:
        _SIFT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(_SIFT_STATE_PATH, json.dumps(state))
    except OSError:
        pass


# How often the per-card cycle runs the eviction sweep. With per-issue
# cards firing dozens of times per scout result, 100 keeps the cadence
# roughly in line with the old per-pass `every-10-fires` rhythm.
SIFT_EVICT_EVERY_CARDS = 100

# After N consecutive cards rejected by the filter pipeline, ask the
# floor to loosen. Cards that find no work (no raw payload, malformed)
# don't count — only cards where we considered the issue and rejected.
SIFT_LOOSEN_EMPTY_STREAK_CARDS = 50


@activity.defn
async def sift_cycle(msg: Message) -> dict:
    """Process ONE issue card from scout. The card payload carries the
    raw gh search result; this activity filters it inline, makes at
    most one fresh gh call (issue_events to detect related PRs, and
    only if cheaper checks pass), and deposits a triaged-inbox entry
    if the issue survives. All pacing between cards happens at the
    SkillActor's should_idle boundary, so the per-card cost is bounded
    and the budget gate has one-call resolution.

    Compare the old per-pass `sift_cycle`: that one ran an entire
    100-issue sweep inside a single activity invocation, bursting
    through the per-actor rate cap before the gate could see it. This
    refactor moves the loop up to scout (one search per card) and the
    per-issue work down to one sift cycle per issue.
    """
    from sweep import budget as _budget
    _budget.set_caller("sift")
    if _budget.is_blocked("sift"):
        observe.event("sift_cycle_skipped", reason="budget_andon",
                      msg_id=msg.msg_id)
        return {"skipped": "budget_andon"}
    if retro_state.is_halted():
        observe.incr("halted_skip:sift")
        return {"skipped": "halted"}
    if control_state.is_paused():
        observe.incr("paused_skip:sift")
        return {"skipped": "paused"}

    state = _load_sift_state()
    state["fires_total"] = int(state.get("fires_total", 0)) + 1

    outcome = await _screen_one_issue(msg)

    # Empty-streak floor loosening — count only cards we actually
    # considered (filtered out an issue). Skipped-for-pause /
    # malformed / triage-full don't move the streak.
    counted = outcome.get("considered", False)
    deposited = bool(outcome.get("deposited"))
    if counted:
        if deposited:
            state["empty_streak"] = 0
        else:
            state["empty_streak"] = int(state.get("empty_streak", 0)) + 1
            if state["empty_streak"] >= SIFT_LOOSEN_EMPTY_STREAK_CARDS:
                try:
                    r = await loosen_floor()
                    if r.get("changed"):
                        state["empty_streak"] = 0
                except Exception as e:
                    observe.event("loosen_floor_failed",
                                  error_type=type(e).__name__,
                                  error=str(e)[:200])

    # Periodic eviction sweep.
    if state["fires_total"] % SIFT_EVICT_EVERY_CARDS == 0:
        try:
            await auto_evict_stale_repos()
        except Exception as e:
            observe.event("auto_evict_failed",
                          error_type=type(e).__name__, error=str(e)[:200])

    _save_sift_state(state)
    outcome["fires_total"] = state["fires_total"]
    outcome["empty_streak"] = state["empty_streak"]
    return outcome


async def _screen_one_issue(msg: Message) -> dict:
    """The per-card filter pipeline. Pure helper — `sift_cycle`
    wraps it with state bookkeeping and andon-clear logic. Returns a
    dict with `considered`, `deposited`, and a `reason`/`status` for
    observability."""
    payload = msg.payload or {}
    raw = payload.get("raw") or {}
    repo = msg.repo
    number = msg.pr
    if not repo or number is None:
        return {"considered": False, "status": "malformed",
                "repo": repo, "issue": number}

    key = seen.issue_key(repo, int(number))
    if seen.has_seen(key):
        return {"considered": False, "status": "seen",
                "repo": repo, "issue": int(number)}

    # Capacity check — don't take the gh hit if the deposit will be
    # refused anyway. Leave unseen so a future card can re-evaluate
    # once triage drains.
    from sweep import inbox_state as _inbox
    if len(_inbox.inbox_states("triaged")["queued"]) >= 10:
        return {"considered": False, "status": "triage_full",
                "repo": repo, "issue": int(number)}

    # Min-age gate — give the maintainer a few minutes to assign or
    # open their own PR before we burn investigate cycles. Don't
    # seen-mark: the next pass should re-evaluate once aged in.
    now = dt.datetime.now(dt.timezone.utc)
    created_iso = raw.get("createdAt") or raw.get("created_at") or ""
    if created_iso:
        try:
            t_created = dt.datetime.fromisoformat(
                created_iso.replace("Z", "+00:00"))
            age_min = (now - t_created).total_seconds() / 60.0
            if age_min < _min_issue_age_minutes():
                return {"considered": False, "status": "too_fresh",
                        "repo": repo, "issue": int(number)}
        except (ValueError, AttributeError):
            pass

    cheap_reason = _cheap_issue_skip(raw)
    if cheap_reason:
        return {"considered": True, "status": f"cheap_{cheap_reason}",
                "deposited": False, "repo": repo, "issue": int(number)}

    meta = _fetch_repo_meta_cheap(repo)  # cached 24h; free after warmup
    if not _passes_deterministic_issue(repo, meta):
        return {"considered": True, "status": "deterministic",
                "deposited": False, "repo": repo, "issue": int(number)}

    # The one always-fresh-ish gh call: cross-reference check. 5min
    # TTL upstream, so consecutive cards on the same issue dedupe.
    if _has_related_pr(repo, int(number)):
        seen.mark_seen(key)
        return {"considered": True, "status": "has_pr",
                "deposited": False, "repo": repo, "issue": int(number)}

    labels = [l.get("name", "") for l in raw.get("labels") or []]
    ic = IssueCandidate(
        repo=repo, number=int(number),
        title=raw.get("title", ""),
        url=raw.get("url", ""),
        labels=labels,
        updated_at=raw.get("updatedAt", "") or raw.get("updated_at", "") or "",
    )
    msg_id = await deposit_issue_to_triaged(ic, complexity="unknown")
    return {"considered": True, "status": "deposited",
            "deposited": bool(msg_id), "msg_id": msg_id,
            "repo": repo, "issue": int(number)}




@activity.defn
async def sift_one_pass(req: SiftRunRequest) -> SiftPassResult:
    """One sweep step. Descend the star cursor by `budget` repos, surface
    actionable issues from the ones that pass lightweight filters."""
    if retro_state.is_halted():
        # Backpressure from the retro pager. Forward pass stops until the
        # human Attends to at least one of the pending SOAP one-pagers.
        observe.incr("halted_skip:sift")
        return SiftPassResult(
            repos_visited=0, repos_processed=0, issues_found=0,
            delivered_msg_ids=[],
            cursor_before=_load_cursor(), cursor_after=_load_cursor(),
            lap_reset=False,
        )
    if control_state.is_paused():
        # Operator-initiated soft-pause. Same no-op shape as the retro
        # halt — in-flight work elsewhere keeps running.
        observe.incr("paused_skip:sift")
        return SiftPassResult(
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

    observe.incr("sift_repos_visited", len(repos))
    observe.incr("sift_repos_processed", processed)
    observe.incr("sift_issues_found", issues_found)
    if lap_reset:
        observe.incr("sift_lap_reset")
    observe.event(
        "sift_pass",
        cursor_before=cursor_before,
        cursor_after=cursor_after,
        repos_visited=len(repos),
        repos_processed=processed,
        issues_found=issues_found,
        lap_reset=lap_reset,
    )

    return SiftPassResult(
        repos_visited=len(repos),
        repos_processed=processed,
        issues_found=issues_found,
        delivered_msg_ids=delivered,
        cursor_before=cursor_before,
        cursor_after=cursor_after,
        lap_reset=lap_reset,
    )
