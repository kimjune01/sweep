"""Scout — searches GitHub for actionable issues, emits one sift
card per raw candidate. Pace: one card from upstream drives ONE gh
search call. Splitting search away from sift is what tames the old
100-call burst: sift now sees one issue per card with the
SkillActor's should_idle gate between them.

The scout has an inbox cursor that alternates between two sources:

  • global — recency-first label search (bug, help-wanted)
  • warm-org — one warm org per cycle, round-robin by index

One cycle = one search = one budget tick. The N issues found are
posted to sift's inbox as cards carrying the raw item in the
payload, so the sift actor does no follow-up search of its own.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from dataclasses import asdict
from pathlib import Path

from temporalio import activity
from temporalio.exceptions import ApplicationError

from sweep import control_state, gh_io, observe, retro_state, warm_orgs
from sweep.io_safe import atomic_write_text
from sweep.types import Message, forward_ledger


SCOUT_INBOX = Path.home() / ".sweep" / "inbox" / "scout.jsonl"
SIFT_INBOX = Path.home() / ".sweep" / "inbox" / "sift.jsonl"

# Repo-size cache + tunables for the auto-evict-by-size gate. Threshold
# default is 1.5GB clone size (gh api returns KB), which catches the
# observed mega-repo class (servo, grafana, chisel, cpython, pytorch,
# nodejs). Tune via ~/.sweep/control/scout_size_threshold_kb. See
# memory/feedback_repo_too_big_is_legit.md for the rationale.
_REPO_SIZE_CACHE = Path.home() / ".sweep" / "control" / "repo_sizes.json"
_SIZE_THRESHOLD_FILE = Path.home() / ".sweep" / "control" / "scout_size_threshold_kb"
_DEFAULT_SIZE_THRESHOLD_KB = 1_500_000  # 1.5 GB
_EVICTED_PATH = Path.home() / ".sweep" / "control" / "sift_evicted.txt"


def _size_threshold_kb() -> int:
    try:
        return max(1, int(_SIZE_THRESHOLD_FILE.read_text().strip()))
    except (OSError, ValueError):
        return _DEFAULT_SIZE_THRESHOLD_KB


def _load_size_cache() -> dict:
    if not _REPO_SIZE_CACHE.exists():
        return {}
    try:
        return json.loads(_REPO_SIZE_CACHE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_size_cache(cache: dict) -> None:
    _REPO_SIZE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    try:
        atomic_write_text(_REPO_SIZE_CACHE, json.dumps(cache))
    except OSError:
        pass


def _repo_size_kb(repo: str) -> int | None:
    """Return repo size in KB per gh api. Cached on disk so repeat
    scout passes don't re-query. Returns None on lookup failure (the
    gate fails-soft: unknown size means proceed)."""
    cache = _load_size_cache()
    if repo in cache:
        return int(cache[repo])
    try:
        r = subprocess.run(
            ["gh", "api", f"repos/{repo}", "--jq", ".size"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            return None
        size = int((r.stdout or "0").strip())
    except (subprocess.TimeoutExpired, ValueError, FileNotFoundError):
        return None
    cache[repo] = size
    _save_size_cache(cache)
    return size


def _auto_evict_by_size(repo: str, size_kb: int, threshold_kb: int) -> None:
    """Append the repo to the eviction list with a size-explanatory
    reason. Idempotent — duplicates in the file are harmless since the
    reader is set-based."""
    line = (
        f"{repo}  # auto-evicted "
        f"{dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')} "
        f"(size {size_kb // 1024}MB > {threshold_kb // 1024}MB threshold)\n"
    )
    _EVICTED_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing = _EVICTED_PATH.read_text() if _EVICTED_PATH.exists() else ""
        if any(ln.split()[0] == repo for ln in existing.splitlines() if ln.strip()):
            return  # already evicted
    except OSError:
        pass
    try:
        with _EVICTED_PATH.open("a") as f:
            f.write(line)
    except OSError:
        pass
SCOUT_CURSOR_PATH = Path.home() / ".sweep" / "cursors" / "scout.json"

# Mechanical search qualifiers shared by both sources. Push every
# filter we can into the gh query so GitHub does the work instead of
# producing per-result follow-up costs to discover the same rejection.
_BASE_QUALIFIERS = ["-linked:pr", "comments:<20"]

# Default recency window for the global search. The retroactive
# widen/recover from the old per-pass model is gone; if the operator
# wants a wider window, write it to ~/.sweep/control/scout_days.
_DEFAULT_DAYS = 30
_DAYS_MAX = 365
_MIN_AGE_MINUTES = 3


def _load_cursor() -> dict:
    if not SCOUT_CURSOR_PATH.exists():
        return {"source": "global", "warm_idx": 0}
    try:
        return json.loads(SCOUT_CURSOR_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {"source": "global", "warm_idx": 0}


def _save_cursor(c: dict) -> None:
    try:
        SCOUT_CURSOR_PATH.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(SCOUT_CURSOR_PATH, json.dumps(c))
    except OSError:
        pass


def _read_days_knob() -> int:
    path = Path.home() / ".sweep" / "control" / "scout_days"
    if not path.exists():
        return _DEFAULT_DAYS
    try:
        v = int(path.read_text().strip())
    except (OSError, ValueError):
        return _DEFAULT_DAYS
    return max(1, min(_DAYS_MAX, v))


async def _emit_sift_card(raw: dict, source: str) -> bool:
    """Write one card to sift.jsonl + signal the actor. Returns
    False on malformed input."""
    repo_obj = raw.get("repository") or {}
    repo = repo_obj.get("nameWithOwner") or repo_obj.get("name_with_owner") or ""
    number = raw.get("number")
    if not repo or not number:
        return False

    # Host-arch compatibility — cheap pattern match on the repo
    # name / description / topics. Zero API calls; only catches the
    # most obvious cases (e.g. "PowerShell"). Less-obvious cases
    # (windows-only matrix entries) fall through to sift's deeper
    # check which is allowed to fetch workflows. Backstop is attest's
    # runtime env precondition.
    try:
        from sweep import host_compat
        repo_desc = (repo_obj.get("description") or "")
        repo_topics = repo_obj.get("repositoryTopics") or repo_obj.get("topics") or []
        if isinstance(repo_topics, list) and repo_topics and isinstance(repo_topics[0], dict):
            repo_topics = [t.get("name", "") for t in repo_topics]
        compat = host_compat.cheap_check(repo, description=repo_desc,
                                          topics=repo_topics)
        if compat.verdict == "incompatible":
            observe.event(
                "scout_host_incompat_drop",
                repo=repo, reason=compat.reason[:200], source=source,
            )
            return False
    except Exception as e:
        # Fail-soft: sift's own check will catch what we miss here.
        observe.event("scout_host_compat_probe_failed",
                      repo=repo, error_type=type(e).__name__,
                      error=str(e)[:200])

    # Size gate — auto-evict mega-repos before any clone. Cost-per-
    # attestation on these is unfavorable (slow clones, slow builds,
    # custom build orchestrators); see memory/feedback_repo_too_big_
    # _is_legit.md. Cached per repo so we pay one gh api call per
    # repo lifetime, not per issue.
    try:
        size_kb = _repo_size_kb(repo)
        threshold_kb = _size_threshold_kb()
        if size_kb is not None and size_kb > threshold_kb:
            _auto_evict_by_size(repo, size_kb, threshold_kb)
            observe.event("scout_size_evict",
                          repo=repo, size_kb=size_kb,
                          threshold_kb=threshold_kb, source=source)
            return False
    except Exception as e:
        observe.event("scout_size_probe_failed", repo=repo,
                      error_type=type(e).__name__, error=str(e)[:200])

    ts = dt.datetime.now(dt.timezone.utc)
    msg_id = f"scout-{repo.replace('/', '-')}-{int(number)}"
    out = Message(
        msg_id=msg_id,
        sender="scout",
        intent="screen",
        repo=repo,
        pr=int(number),
        branch=None,
        payload={"raw": raw, "source": source},
        ts=ts.isoformat(),
    )
    SIFT_INBOX.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(SIFT_INBOX, "a") as f:
            f.write(json.dumps(asdict(out)) + "\n")
    except OSError as e:
        observe.event("scout_emit_failed",
                      error_type=type(e).__name__, error=str(e)[:200])
        return False
    # Signal the sift actor. Best-effort; the jsonl write is the
    # durable record and the leakdog drain catches missed signals on
    # restart. Import here so the workflow side doesn't drag the
    # signaling module into its sandbox.
    try:
        from sweep.activities.pr_state import _signal_actor
        await _signal_actor("sift", out)
    except Exception as e:
        observe.event("scout_signal_failed", msg_id=msg_id,
                      error_type=type(e).__name__, error=str(e)[:200])
    return True


@activity.defn
async def scout_cycle(msg: Message) -> dict:
    """One gh search, alternating global ↔ warm-org via the cursor.
    Emits one sift card per raw issue.

    Payload is unused — the card is just the trigger. What to do is
    fixed (advance one position on the source-cursor and search).
    """
    from sweep import budget as _budget
    _budget.set_caller("scout")
    if retro_state.is_halted():
        observe.incr("halted_skip:scout")
        return {"emitted": 0, "skipped": "halted"}
    if control_state.is_paused():
        observe.incr("paused_skip:scout")
        return {"emitted": 0, "skipped": "paused"}
    if _budget.is_blocked("scout"):
        observe.event("scout_cycle_skipped", reason="budget_andon")
        return {"emitted": 0, "skipped": "budget_andon"}

    cursor = _load_cursor()
    now = dt.datetime.now(dt.timezone.utc)
    age_floor = now - dt.timedelta(minutes=_MIN_AGE_MINUTES)
    age_floor_iso = age_floor.strftime('%Y-%m-%dT%H:%M:%SZ')
    days = _read_days_knob()
    cutoff = (now - dt.timedelta(days=days)).strftime('%Y-%m-%d')
    extra = _BASE_QUALIFIERS + [f"created:<{age_floor_iso}"]

    source = cursor.get("source", "global")
    raw: list[dict] = []
    try:
        if source == "global":
            raw = gh_io.search_issues(
                labels=["bug", "help-wanted"],
                state="open", no_assignee=True, archived=None,
                created_after=cutoff,
                extra_qualifiers=extra,
                sort="created", order="desc",
                limit=100,
            )
            cursor["source"] = "warm"
        else:
            try:
                warm_state = warm_orgs.state()
                orgs = list((warm_state.get("orgs") or {}).keys())
            except Exception:
                orgs = []
            if not orgs:
                cursor["source"] = "global"
                _save_cursor(cursor)
                observe.event("scout_cycle", source="warm",
                              raw=0, emitted=0, note="no warm orgs")
                return {"source": "warm", "raw": 0, "emitted": 0,
                        "note": "no warm orgs"}
            idx = int(cursor.get("warm_idx", 0)) % len(orgs)
            org = orgs[idx]
            warm_cutoff = (now - dt.timedelta(days=max(90, days * 3))
                           ).strftime('%Y-%m-%d')
            try:
                raw = gh_io.search_issues(
                    state="open", no_assignee=True, archived=None,
                    created_after=warm_cutoff,
                    owner=org,
                    extra_qualifiers=_BASE_QUALIFIERS,
                    sort="created", order="desc",
                    limit=30,
                )
            except Exception as e:
                observe.event("scout_warm_search_failed", org=org,
                              error_type=type(e).__name__,
                              error=str(e)[:200])
                raw = []
            cursor["warm_idx"] = (idx + 1) % len(orgs)
            cursor["source"] = "global"
    except subprocess.CalledProcessError as e:
        raise ApplicationError(
            f"gh search failed ({source}): {(e.stderr or '')[:300]}",
            non_retryable=False,
        )

    _save_cursor(cursor)

    emitted = 0
    for it in raw:
        if await _emit_sift_card(it, source):
            emitted += 1

    observe.event("scout_cycle", source=source, raw=len(raw),
                  emitted=emitted)
    return {"source": source, "raw": len(raw), "emitted": emitted}


async def kick_scout_card(sender: str, incoming: Message | None = None) -> str | None:
    """Drop one trigger card on scout's inbox and signal it.

    Fires from leakdog (heartbeat when sift's inbox runs dry) and
    from triage acks (downstream consumed; refill). Mirrors the old
    Sift no longer has a "schedule a search" card type, only
    "screen this issue" — that scheduling responsibility moved here.
    """
    from sweep.activities.pr_state import _signal_actor
    ts = dt.datetime.now(dt.timezone.utc)
    msg = Message(
        msg_id=f"scout-card-{sender}-{ts.strftime('%Y%m%dT%H%M%S%f')}",
        sender=sender,
        intent="card",
        repo="", pr=None, branch=None,
        payload={"reason": f"pull from {sender}"},
        ts=ts.isoformat(),
        ledger=forward_ledger(incoming),
    )
    SCOUT_INBOX.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(SCOUT_INBOX, "a") as f:
            f.write(json.dumps(asdict(msg)) + "\n")
    except OSError as e:
        observe.event("scout_card_write_failed",
                      error_type=type(e).__name__, error=str(e)[:200])
        return None
    return await _signal_actor("scout", msg)
