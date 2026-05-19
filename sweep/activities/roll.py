"""Roll — d20 stochastic search. Each cycle rolls three independent
dice combinations, runs three gh searches, pools the results, and
emits one sift card per surviving candidate.

d12 Language × d8 Signal × d6 Sort+Size = 576 query shapes. The dice
are uniform and stateless. The filter (eviction, seen-set, host-compat,
size) is deterministic and lives downstream of the dice — see
skills/sift.md §198 (d20 stochastic search) for the policy rationale:

  > The dice don't learn — you can't overfit a d20. The quality comes
  > from the filter. They don't talk to each other.

Replaces the old scout actor's fixed-query path (labels=[bug],
stars:>=200, comments:<20). That path narrowed to empty under load;
the dice restore breadth as the substrate's exploration source.

One cycle = three rolls = up to three searches. Each roll re-rolls
up to MAX_REROLLS_PER_LEG times if the search returns zero raw
candidates (likely a dead query shape). After re-rolls exhausted,
the leg moves on. No memory; the next cycle rolls fresh.
"""

from __future__ import annotations

import datetime as dt
import json
import random
import subprocess
from dataclasses import asdict
from pathlib import Path

from temporalio import activity
from temporalio.exceptions import ApplicationError

from sweep import control_state, gh_io, observe, retro_state
from sweep.types import Message, forward_ledger


ROLL_INBOX = Path.home() / ".sweep" / "inbox" / "roll.jsonl"
SIFT_INBOX = Path.home() / ".sweep" / "inbox" / "sift.jsonl"

# Repo-size cache + tunables for the auto-evict-by-size gate. Same
# cache file as the old scout path used — survives the rename so the
# 142-entry size cache isn't re-queried after retirement.
_REPO_SIZE_CACHE = Path.home() / ".sweep" / "control" / "repo_sizes.json"
_SIZE_THRESHOLD_FILE = Path.home() / ".sweep" / "control" / "roll_size_threshold_kb"
_DEFAULT_SIZE_THRESHOLD_KB = 1_500_000  # 1.5 GB
_EVICTED_PATH = Path.home() / ".sweep" / "control" / "sift_evicted.txt"

# Recency window (default 30d, operator-tunable via
# ~/.sweep/control/roll_days). Mirrors the old scout_days knob.
_DEFAULT_DAYS = 30
_DAYS_MAX = 365
_MIN_AGE_MINUTES = 3

# Per-roll search caps. Three rolls × 30 = up to 90 raw results per
# cycle; the deterministic filter chain culls most.
_PER_ROLL_LIMIT = 30
_ROLLS_PER_CYCLE = 3
_MAX_REROLLS_PER_LEG = 3

# Minimum stars hard-floor across all rolled queries. Same threshold
# sift's FLOOR uses as backstop; matches operator's minimum-attention
# bar from feedback memory.
_STARS_FLOOR = 200


# ── Dice tables ───────────────────────────────────────────────────────
#
# d12 Language — language:<l> qualifier filters issue's repo language.
# Twelve mainstream toolchains; deliberately excludes JS (too broad)
# and shell (too rarely a substantive bug surface).
_D12_LANGUAGE = [
    "rust", "go", "python", "typescript", "cpp", "java",
    "csharp", "kotlin", "ruby", "zig", "swift", "lua",
]

# Bootstrap d12 prior — counts of merged PRs by repo-language across
# the operator's 111-merge corpus (2026-05-19 snapshot). The OSS hygraph
# (~/.sweep/repo-hypotheses/ + HYPOTHESIS_GRAPH.md) treats this as the
# starting belief about "where mergeable work has lived." Languages
# absent from the corpus get the floor weight (PROBE_FLOOR) so they
# still get probed via the uniform tendril budget. See feedback memory:
# slime mold = explore + reinforce + probe.
_D12_LANGUAGE_PRIOR = {
    "rust":       32,
    "python":     16,
    "go":         13,
    "cpp":         6,
    "typescript":  5,
    "swift":       2,
    "ruby":        1,
    "zig":         1,
    "java":        1,   # floor
    "csharp":      1,   # floor
    "kotlin":      1,   # floor
    "lua":         1,   # floor
}
# Fraction of rolls that sample d12 uniformly regardless of trail —
# the slime mold's probe tendrils. Keeps dead-branch detection alive
# when GitHub's topology shifts. 0.10 = 1 in 10 rolls is exploratory.
_PROBE_FRACTION = 0.10
# Per-combo trail file. Stores {survived, rolled} for each (lang, signal,
# sort) triple. Updated per emit by `_credit_trail`.
_TRAIL_PATH = Path.home() / ".sweep" / "state" / "roll_trail.json"
# EWMA-style decay applied at write time so stale wins lose dominance.
# Combos that haven't been credited recently fade toward the prior.
_TRAIL_HALF_LIFE_DAYS = 7  # matches the "ran out in a week" timeline

# d8 Signal — label/comment shapes that act as proxies for "this is
# a fixable issue." Each shape encodes a different theory of where
# value lives. Labels with spaces must travel as `labels=[...]` (gh
# `--label` flag) — positional `label:"x y"` doesn't survive shell
# round-tripping through gh's search query parser.
#   unassigned    — nobody's working on it, no claim to step on
#   silent        — no maintainer ack, may need first comment
#   discussed     — already triaged in the thread, context is rich
#   gfi           — explicitly tagged as approachable
#   help          — maintainer signalled openness to outside help
#   upvoted       — community-validated importance
#   kind/bug      — Kubernetes convention (and look-alikes)
#   broad         — any label containing "bug" (catch-all)
_D8_SIGNAL = [
    {"name": "unassigned", "labels": ["bug"],              "qual": ["no:assignee"]},
    {"name": "silent",     "labels": ["bug"],              "qual": ["comments:0"]},
    {"name": "discussed",  "labels": ["bug"],              "qual": ["comments:>5"]},
    {"name": "gfi",        "labels": ["good first issue"], "qual": []},
    {"name": "help",       "labels": ["help wanted"],      "qual": []},
    {"name": "upvoted",    "labels": ["bug"],              "qual": ["reactions:>3"]},
    {"name": "kindbug",    "labels": ["kind/bug"],         "qual": []},
    {"name": "broad",      "labels": [],                   "qual": ["label:bug,Bug,bugs"]},
]

# d6 Sort+Size — sort dimension + a star band. The star band shapes
# repo size; bands all sit ≥_STARS_FLOOR so the floor invariant holds.
#   mid    = 200..2000 stars
#   small  = 200..500
#   large  = >2000
#   any    = >=200 (open-ended)
_D6_SORT_SIZE = [
    {"name": "updated_mid",    "sort": "updated",   "stars": "200..2000"},
    {"name": "updated_small",  "sort": "updated",   "stars": "200..500"},
    {"name": "reactions_lg",   "sort": "reactions", "stars": ">2000"},
    {"name": "created_any",    "sort": "created",   "stars": f">={_STARS_FLOOR}"},
    {"name": "comments_mid",   "sort": "comments",  "stars": "200..2000"},
    {"name": "updated_lg",     "sort": "updated",   "stars": ">2000"},
]


def _size_threshold_kb() -> int:
    try:
        return max(1, int(_SIZE_THRESHOLD_FILE.read_text().strip()))
    except (OSError, ValueError):
        return _DEFAULT_SIZE_THRESHOLD_KB


def _read_days_knob() -> int:
    path = Path.home() / ".sweep" / "control" / "roll_days"
    if not path.exists():
        return _DEFAULT_DAYS
    try:
        v = int(path.read_text().strip())
    except (OSError, ValueError):
        return _DEFAULT_DAYS
    return max(1, min(_DAYS_MAX, v))


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
        from sweep.io_safe import atomic_write_text
        atomic_write_text(_REPO_SIZE_CACHE, json.dumps(cache))
    except OSError:
        pass


def _repo_size_kb(repo: str) -> int | None:
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
    line = (
        f"{repo}  # auto-evicted "
        f"{dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')} "
        f"(size {size_kb // 1024}MB > {threshold_kb // 1024}MB threshold)\n"
    )
    _EVICTED_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing = _EVICTED_PATH.read_text() if _EVICTED_PATH.exists() else ""
        if any(ln.split()[0] == repo for ln in existing.splitlines() if ln.strip()):
            return
    except OSError:
        pass
    try:
        with _EVICTED_PATH.open("a") as f:
            f.write(line)
    except OSError:
        pass


# ── Slime-mold trail ─────────────────────────────────────────────────
#
# Per-combo {survived, rolled} EWMA. Yield = survived / max(rolled, 1).
# Weighted dice combine three sources:
#   - language prior (bootstrap from 111-merge corpus)
#   - trail yield  (forward observations)
#   - probe budget (10% uniform per dice axis)
# Binary cost gates (eviction, host-compat, size) live downstream of
# the dice unchanged — they're the hard floor. The trail is the soft
# layer that biases sampling toward fruitful combos.

def _combo_key(lang: str, signal: str, sort_size: str) -> str:
    return f"{lang}|{signal}|{sort_size}"


def _load_trail() -> dict:
    if not _TRAIL_PATH.exists():
        return {}
    try:
        return json.loads(_TRAIL_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _save_trail(trail: dict) -> None:
    _TRAIL_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        from sweep.io_safe import atomic_write_text
        atomic_write_text(_TRAIL_PATH, json.dumps(trail, indent=2))
    except OSError:
        pass


def _credit_trail(combo_key: str, survived: int, rolled: int) -> None:
    """Record one cycle's outcome for `combo_key`. EWMA-style: existing
    counts get halved per half-life-day since last write, then we add
    the new observation. This makes fresh evidence dominate stale wins
    without ever zeroing — the slime-mold trail evaporates, it doesn't
    cut."""
    trail = _load_trail()
    now = dt.datetime.now(dt.timezone.utc)
    entry = trail.get(combo_key) or {"survived": 0.0, "rolled": 0.0,
                                      "updated": now.isoformat()}
    try:
        last = dt.datetime.fromisoformat(entry["updated"])
        days_elapsed = max(0.0, (now - last).total_seconds() / 86400.0)
    except (ValueError, KeyError):
        days_elapsed = 0.0
    decay = 0.5 ** (days_elapsed / _TRAIL_HALF_LIFE_DAYS) if _TRAIL_HALF_LIFE_DAYS > 0 else 1.0
    entry["survived"] = float(entry.get("survived", 0)) * decay + survived
    entry["rolled"] = float(entry.get("rolled", 0)) * decay + rolled
    entry["updated"] = now.isoformat()
    trail[combo_key] = entry
    _save_trail(trail)


def _trail_yield(combo_key: str) -> float:
    """Yield score for one combo. Returns 0.0 if unseen — the prior
    handles bootstrap for language; signal/sort have no prior so unseen
    combos rely on the uniform probe budget."""
    trail = _load_trail()
    entry = trail.get(combo_key)
    if not entry:
        return 0.0
    rolled = float(entry.get("rolled", 0))
    if rolled <= 0:
        return 0.0
    return float(entry.get("survived", 0)) / rolled


def _weighted_choice(items: list, weights: list[float]) -> object:
    """Sample one item proportional to weights. Falls back to uniform
    if all weights are zero (defensive — shouldn't happen with the
    floor weights in the prior, but covers a corrupted trail file)."""
    total = sum(weights)
    if total <= 0:
        return random.choice(items)
    r = random.random() * total
    acc = 0.0
    for item, w in zip(items, weights):
        acc += w
        if r <= acc:
            return item
    return items[-1]


def _roll_query() -> dict:
    """Roll three dice with slime-mold weighting + probe budget.

    Each axis independently rolls probe-or-weighted:
      - With probability _PROBE_FRACTION: uniform random (exploration).
      - Otherwise: weighted by (language prior × trail yield) for d12,
        and by trail yield for d8 / d6.

    Returns {sort, labels[], qualifiers[], names, combo_key}. The
    combo_key threads through `_emit_sift_card` so trail credit lands
    on the right entry."""
    # d12 — language: prior × trail-yield (per-language average)
    if random.random() < _PROBE_FRACTION:
        lang = random.choice(_D12_LANGUAGE)
    else:
        weights = []
        for l in _D12_LANGUAGE:
            prior = _D12_LANGUAGE_PRIOR.get(l, 1)
            # Average trail yield across signal/sort for this language.
            # +1 in the multiplier avoids cold-start zeroing the prior.
            keys = [_combo_key(l, s["name"], ss["name"])
                    for s in _D8_SIGNAL for ss in _D6_SORT_SIZE]
            yields = [_trail_yield(k) for k in keys]
            avg_yield = sum(yields) / len(yields) if yields else 0.0
            weights.append(prior * (1.0 + avg_yield))
        lang = _weighted_choice(_D12_LANGUAGE, weights)

    # d8 — signal: trail yield conditioned on chosen language.
    if random.random() < _PROBE_FRACTION:
        signal = random.choice(_D8_SIGNAL)
    else:
        weights = []
        for s in _D8_SIGNAL:
            keys = [_combo_key(lang, s["name"], ss["name"])
                    for ss in _D6_SORT_SIZE]
            yields = [_trail_yield(k) for k in keys]
            avg_yield = sum(yields) / len(yields) if yields else 0.0
            # Uniform baseline + yield bonus — every signal stays
            # samplable while fruitful ones get over-sampled.
            weights.append(1.0 + 4.0 * avg_yield)
        signal = _weighted_choice(_D8_SIGNAL, weights)

    # d6 — sort+size: trail yield conditioned on (lang, signal).
    if random.random() < _PROBE_FRACTION:
        sort_size = random.choice(_D6_SORT_SIZE)
    else:
        weights = []
        for ss in _D6_SORT_SIZE:
            y = _trail_yield(_combo_key(lang, signal["name"], ss["name"]))
            weights.append(1.0 + 4.0 * y)
        sort_size = _weighted_choice(_D6_SORT_SIZE, weights)

    qualifiers = list(signal["qual"]) + [
        f"language:{lang}",
        f"stars:{sort_size['stars']}",
        "-linked:pr",
    ]
    return {
        "sort": sort_size["sort"],
        "labels": list(signal["labels"]),
        "qualifiers": qualifiers,
        "names": {"language": lang, "signal": signal["name"],
                  "sort_size": sort_size["name"]},
        "combo_key": _combo_key(lang, signal["name"], sort_size["name"]),
    }


async def _emit_sift_card(raw: dict, source: str) -> bool:
    """Write one card to sift.jsonl + signal the actor. Returns
    False on malformed input or filter rejection."""
    repo_obj = raw.get("repository") or {}
    repo = repo_obj.get("nameWithOwner") or repo_obj.get("name_with_owner") or ""
    number = raw.get("number")
    if not repo or not number:
        return False

    # Eviction gate — sift_evicted.txt + sift_kill_list.txt. Filter at
    # source so sift's evicted-skip path doesn't burn ticks.
    try:
        from sweep.activities.sift import _on_evicted_list, _on_kill_list
        if _on_evicted_list(repo) or _on_kill_list(repo):
            observe.event("roll_evicted_drop", repo=repo, source=source)
            return False
    except Exception:
        pass

    # Seen-set gate — mark eagerly after write, drop early on re-surface.
    try:
        from sweep import seen
        if seen.has_seen(seen.issue_key(repo, int(number))):
            observe.event("roll_seen_drop", repo=repo, issue=number,
                          source=source)
            return False
    except Exception:
        pass

    # Host-arch compatibility — cheap pattern match, no API calls.
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
                "roll_host_incompat_drop",
                repo=repo, reason=compat.reason[:200], source=source,
            )
            return False
    except Exception as e:
        observe.event("roll_host_compat_probe_failed",
                      repo=repo, error_type=type(e).__name__,
                      error=str(e)[:200])

    # Size gate — auto-evict mega-repos. Cached per-repo.
    try:
        size_kb = _repo_size_kb(repo)
        threshold_kb = _size_threshold_kb()
        if size_kb is not None and size_kb > threshold_kb:
            _auto_evict_by_size(repo, size_kb, threshold_kb)
            observe.event("roll_size_evict",
                          repo=repo, size_kb=size_kb,
                          threshold_kb=threshold_kb, source=source)
            return False
    except Exception as e:
        observe.event("roll_size_probe_failed", repo=repo,
                      error_type=type(e).__name__, error=str(e)[:200])

    ts = dt.datetime.now(dt.timezone.utc)
    msg_id = f"roll-{repo.replace('/', '-')}-{int(number)}"
    out = Message(
        msg_id=msg_id,
        sender="roll",
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
        observe.event("roll_emit_failed",
                      error_type=type(e).__name__, error=str(e)[:200])
        return False
    try:
        from sweep.activities.pr_state import _signal_actor
        await _signal_actor("sift", out)
    except Exception as e:
        observe.event("roll_signal_failed", msg_id=msg_id,
                      error_type=type(e).__name__, error=str(e)[:200])
    try:
        from sweep import seen
        seen.mark_seen(seen.issue_key(repo, int(number)))
    except Exception:
        pass
    return True


def _search_one_roll(plan: dict, age_floor_iso: str, cutoff: str) -> list[dict]:
    """Execute one rolled query against gh. Returns raw hits."""
    qualifiers = list(plan["qualifiers"]) + [f"created:<{age_floor_iso}"]
    try:
        return gh_io.search_issues(
            labels=plan.get("labels") or None,
            state="open",
            no_assignee=False,  # signal-shape may already encode assignee
            archived=None,
            created_after=cutoff,
            extra_qualifiers=qualifiers,
            sort=plan["sort"], order="desc",
            limit=_PER_ROLL_LIMIT,
        )
    except subprocess.CalledProcessError as e:
        observe.event("roll_search_failed",
                      query_names=plan.get("names"),
                      error=(e.stderr or "")[:200])
        return []


@activity.defn
async def roll_cycle(msg: Message) -> dict:
    """One cycle = up to _ROLLS_PER_CYCLE independent dice rolls,
    each running one gh search. Pool results, emit one sift card per
    survivor.

    Payload is unused; the card is just the trigger. What to do is
    fixed: roll 3 × (d12 × d8 × d6) → search → emit.
    """
    from sweep import budget as _budget
    _budget.set_caller("roll")
    if retro_state.is_halted():
        observe.incr("halted_skip:roll")
        return {"emitted": 0, "skipped": "halted"}
    if control_state.is_paused():
        observe.incr("paused_skip:roll")
        return {"emitted": 0, "skipped": "paused"}
    if _budget.is_blocked("roll"):
        observe.event("roll_cycle_skipped", reason="budget_andon")
        return {"emitted": 0, "skipped": "budget_andon"}

    # Self-throttle. Rope pulls at 60s as an independent demand signal;
    # we don't want every pull to fire a 3-12-call search burst. Instead
    # we pace ourselves to the budget share: at cap, skip; below cap,
    # run. Over a rolling window this converges to roughly share-cap
    # usage. The user-facing intent: "approximately meet your budget"
    # — fire enough to use the share, no more.
    used = _budget.share_used("roll")
    if used >= 1.0:
        observe.event("roll_cycle_skipped", reason="self_throttle",
                      share_used=round(used, 3))
        return {"emitted": 0, "skipped": "self_throttle",
                "share_used": round(used, 3)}

    now = dt.datetime.now(dt.timezone.utc)
    age_floor = now - dt.timedelta(minutes=_MIN_AGE_MINUTES)
    age_floor_iso = age_floor.strftime('%Y-%m-%dT%H:%M:%SZ')
    days = _read_days_knob()
    cutoff = (now - dt.timedelta(days=days)).strftime('%Y-%m-%d')

    # Per-leg attribution. `leg_origin[(repo,number)] = combo_key` for
    # the FIRST leg that surfaced this issue. Lossy when an issue appears
    # in multiple legs (credit goes to first finder) but simpler than
    # multi-attribution and good enough for the EWMA-shaped trail.
    pooled: list[dict] = []
    leg_origin: dict[tuple[str, int], str] = {}
    rolls_record: list[dict] = []
    for leg in range(_ROLLS_PER_CYCLE):
        plan = _roll_query()
        raw = _search_one_roll(plan, age_floor_iso, cutoff)
        rerolls = 0
        while not raw and rerolls < _MAX_REROLLS_PER_LEG:
            rerolls += 1
            plan = _roll_query()
            raw = _search_one_roll(plan, age_floor_iso, cutoff)
        rolls_record.append({
            "leg": leg, "rerolls": rerolls,
            "names": plan["names"], "raw": len(raw),
            "combo_key": plan["combo_key"],
        })
        for r in raw:
            repo_obj = r.get("repository") or {}
            repo = repo_obj.get("nameWithOwner") or repo_obj.get("name_with_owner") or ""
            number = r.get("number")
            if not repo or not number:
                continue
            k = (repo, int(number))
            if k not in leg_origin:
                leg_origin[k] = plan["combo_key"]
            pooled.append(r)

    # Pool-level dedup by (repo, number) before emit. Same issue may
    # surface across dice combinations (e.g. a Rust label:bug issue
    # appearing in both "updated_mid" and "comments_mid" sorts).
    seen_keys: set[tuple[str, int]] = set()
    deduped: list[dict] = []
    for raw in pooled:
        repo_obj = raw.get("repository") or {}
        repo = repo_obj.get("nameWithOwner") or repo_obj.get("name_with_owner") or ""
        number = raw.get("number")
        if not repo or not number:
            continue
        key = (repo, int(number))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(raw)

    # Emit + track per-combo survivor counts. Yield = survived after
    # binary filter chain (eviction, seen, host-compat, size). True
    # quality signal (merged PR) arrives weeks later; for now this is
    # the cheapest survival proxy that updates within one cycle.
    emitted = 0
    survivors_by_combo: dict[str, int] = {}
    for it in deduped:
        repo_obj = it.get("repository") or {}
        repo = repo_obj.get("nameWithOwner") or repo_obj.get("name_with_owner") or ""
        number = it.get("number") or 0
        combo = leg_origin.get((repo, int(number)), "")
        if await _emit_sift_card(it, source="roll"):
            emitted += 1
            if combo:
                survivors_by_combo[combo] = survivors_by_combo.get(combo, 0) + 1

    # Credit each rolled leg's combo with its outcome. A leg that
    # rolled but contributed nothing to deduped (raw==0, or all dupes,
    # or all filtered) still gets a `rolled=1, survived=0` debit — the
    # trail learns from misses too.
    seen_combos: set[str] = set()
    for r in rolls_record:
        combo = r.get("combo_key", "")
        if not combo or combo in seen_combos:
            continue
        seen_combos.add(combo)
        _credit_trail(combo, survivors_by_combo.get(combo, 0), 1)

    observe.event("roll_cycle", rolls=rolls_record,
                  pooled=len(pooled), deduped=len(deduped),
                  emitted=emitted, survivors_by_combo=survivors_by_combo)
    return {"rolls": rolls_record, "pooled": len(pooled),
            "deduped": len(deduped), "emitted": emitted,
            "survivors_by_combo": survivors_by_combo}


async def kick_roll_card(sender: str, incoming: Message | None = None) -> str | None:
    """Drop one trigger card on roll's inbox and signal it. Fired by
    rope (pull-signal controller) and leakdog (bootstrap heartbeat).

    Tug coalescing: rope's tug is an ephemeral demand signal — if there
    is already a pending tug card waiting on roll, additional tugs are
    no-ops. Without this, leakdog/rope accumulate one card per tick
    while roll is throttled, and the inbox grows unboundedly. Roll only
    needs ONE pending card to fire its next cycle; everything beyond
    that is wasted ledger noise."""
    from sweep.activities.pr_state import _signal_actor
    try:
        from sweep.inbox_state import inbox_states
        pending = inbox_states("roll").get("queued", [])
        if any(m.get("intent") == "card" for m in pending):
            observe.event("roll_tug_coalesced", sender=sender,
                          pending=len(pending))
            return None
    except Exception:
        pass  # fail-open: if the read fails, fall through to enqueue
    ts = dt.datetime.now(dt.timezone.utc)
    msg = Message(
        msg_id=f"roll-card-{sender}-{ts.strftime('%Y%m%dT%H%M%S%f')}",
        sender=sender,
        intent="card",
        repo="", pr=None, branch=None,
        payload={"reason": f"pull from {sender}"},
        ts=ts.isoformat(),
        ledger=forward_ledger(incoming),
    )
    ROLL_INBOX.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(ROLL_INBOX, "a") as f:
            f.write(json.dumps(asdict(msg)) + "\n")
    except OSError as e:
        observe.event("roll_card_write_failed",
                      error_type=type(e).__name__, error=str(e)[:200])
        return None
    return await _signal_actor("roll", msg)
