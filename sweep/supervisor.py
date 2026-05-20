"""Supervisor — the encoding loop, one level up, as a higher-order function.

The trilogy (june.kim/encoding-expertise, /supervisor, /asymptote-learning)
frames every classifier as a five-stratum shell (precondition, postcondition,
CLI tool, cache, LLM residue) around a thin Sonnet nucleus. The *supervisor*
is the same primitive applied to the classifiers themselves: it reads their
two attention channels (operator inbox = ambiguous cases, andon log =
false-knowns), finds patterns that recur >= N times, and proposes new
structural artifacts that would have prevented each occurrence — hoisting
determinism out of the nucleus whenever it can prove the hoist is safe.

This module is the higher-ordered function the post describes: `supervise`
takes a `SupervisorSpec` and runs one pass. switch / remit / compose are
three instantiations; a public-corpus run (e.g. an exemplary contributor's
review register) is a fourth, where the only thing that changes is the
`gather` callable. Same loop, different parameterization — Supervisor² is
"the same shape, one level up."

Deliberately standalone and propose-only:
  - No Temporal registration, no worker wiring, no metronome cadence. A pass
    runs in-process via `supervise(spec)` or `sweep supervisor run`. The
    isolation keeps an unproven loop away from the humming substrate.
  - When a pattern is hoistable, the pass writes a staged proposal +
    replay evidence to ~/.sweep/supervisor/proposals/ and an HITL card to
    human.jsonl. It never edits source. The operator approves, then applies.
    Auto-apply behind the replay gate is a later flag, off by default.

The five strata, at the supervisor level:
  - Identity (precondition): only clusters with >= min_occurrences survive.
  - Legal moves (postcondition): Sonnet must return one ACTION_ENUM label.
  - Live state (CLI tool): the gather/history callables fetch ground truth
    (local jsonl, `gh`) instead of letting the model recall it.
  - Repeats (cache): rejected proposals are remembered so we don't re-propose.
  - Residue (LLM nucleus): the genuinely fuzzy "is this hoistable, and how"
    call, plus the idempotence-wall replay check.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import subprocess
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

SUPERVISOR_DIR = Path.home() / ".sweep" / "supervisor"
PROPOSALS_DIR = SUPERVISOR_DIR / "proposals"
REJECT_CACHE = SUPERVISOR_DIR / "rejected.json"
RESIDUE_LOG = SUPERVISOR_DIR / "residue.jsonl"
HUMAN_INBOX = Path.home() / ".sweep" / "inbox" / "human.jsonl"

# The whole loop is one switch/case over four cases, cheapest-first — the
# trilogy's cascade tail: expert > agent > supervisor > human. Each case
# claims the cluster only if the cheaper one to its left can't.
#   expert     — a stable distinction the deterministic shell can own
#                TRIVIALLY: a pure expert-system rule, no judgment, no replay
#                subtlety. Cheapest possible hoist; operator can fast-approve.
#   agent      — irreducibly fuzzy; the LLM nucleus already handles it as well
#                as anything can. Leave it in the agent, encode nothing.
#   supervisor — stable, but the encoding must be CONSTRUCTED and replay-gated.
#                Genuine supervisor work: propose a hoist, prove it idempotent.
#   human      — the supervisor can't tell if it's stable; surface to HITL.
# The asymptote: `expert` starts trivial and grows monotonically to subsume
# the rest. Each applied proposal becomes part of the deterministic shell, so
# clusters that were `supervisor` (then `agent`) work this pass become `expert`
# (or vanish) on the next. Run the loop to a fixed point and the residue left
# for agent/human is exactly the part of the problem that has no stable shape.
CASE_ENUM = ("expert", "agent", "supervisor", "human")
_PROPOSAL_CASES = ("expert", "supervisor")  # both stage a hoist proposal

# When the case is `expert`/`supervisor`, which stratum the hoist lands in
# (cheapest-first, the same order the classifiers themselves cascade).
# Determinism is clamped from BOTH sides of the nucleus:
#   - OUTSIDE the agent: precondition (reject off-shape input at the door)
#     and postcondition (wall the output enum) wrap the model.
#   - INSIDE the agent: cli-tool — the supervisor BUILDS a tool the agent
#     calls mid-judgment, so a fact the model used to guess is fetched
#     deterministically. The agent keeps the judgment; the tool removes the
#     guess. cache-key sits between (memoize the whole decision on true input).
STRATA = (
    "precondition",   # outside: reject an off-shape input at the door
    "cache-key",      # memoize the decision on a key derived from true input
    "cli-tool",       # inside: a tool the agent calls for deterministic ground truth
    "postcondition",  # outside: tighten the output contract / enum wall
)

_MODEL = "claude-sonnet-4-6"
_WORD = re.compile(r"[a-z]+")


# ---------------------------------------------------------------- types

@dataclass
class Observation:
    """One thing that happened on an attention channel. `signature` is the
    cheap, deterministic clustering key (so grouping costs no model call);
    `detail` is the human-readable evidence quoted into proposals; `case` is
    the identity of the underlying case (e.g. "repo#pr") so support counts
    DISTINCT cases, not the same card re-surfaced N times."""
    signature: str
    detail: str
    source: str  # "andon" | "inbox" | "corpus" | "regret"
    case: str | None = None


@dataclass
class SupervisorSpec:
    """The parameterization. Everything that differs between supervising
    switch vs remit vs a public corpus lives here; `supervise` is invariant."""
    name: str
    goal: str  # the gradient: every case==human call asks "does this serve the goal?"
    gather: Callable[[], list[Observation]]      # corpus loader (attention channels)
    history: Callable[[], list[dict]]            # replay corpus (past, possibly-labeled decisions)
    min_occurrences: int = 3                     # the N>=3 precondition
    max_clusters: int = 8                        # attention budget per pass (loudest first)
    model: str = _MODEL


# ---------------------------------------------------------------- Sonnet shim

def _ask_sonnet(system: str, user: str, model: str, timeout: int = 90) -> dict | None:
    """One Sonnet call returning parsed JSON, or None on any failure. Mirrors
    switch.py's subprocess discipline: Max-plan routing via env-pop, single
    shot (the supervisor is not latency-critical), JSON-only contract."""
    from sweep.claude_subprocess import env_without_api_key
    try:
        proc = subprocess.run(
            ["claude", "--print", "--model", model,
             "--append-system-prompt", system, user],
            capture_output=True, text=True, timeout=timeout, check=False,
            env=env_without_api_key(),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return _parse_json(proc.stdout or "")


def _parse_json(text: str) -> dict | None:
    text = text.strip()
    if not text:
        return None
    # Tolerate ```json fences and leading prose; grab the first {...} block.
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------- cache

def _load_rejects() -> dict:
    if not REJECT_CACHE.exists():
        return {}
    try:
        return json.loads(REJECT_CACHE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_rejects(d: dict) -> None:
    REJECT_CACHE.parent.mkdir(parents=True, exist_ok=True)
    REJECT_CACHE.write_text(json.dumps(d, indent=2, sort_keys=True))


def _cluster_key(spec_name: str, signature: str) -> str:
    return hashlib.sha256(f"{spec_name}::{signature}".encode()).hexdigest()[:16]


# ---------------------------------------------------------------- the loop

def supervise(spec: SupervisorSpec, *, verbose: bool = False) -> dict:
    """Run one supervisor pass over `spec`. Returns a summary dict and, as a
    side effect, writes proposals + HITL cards + a residue log.

    The five strata, in order, cheapest first — exactly the cascade the
    classifiers themselves use, applied to the classifiers."""
    PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
    rejects = _load_rejects()

    # --- gather + group + precondition (N >= min_occurrences) ---
    observations = spec.gather()
    clusters: dict[str, list[Observation]] = defaultdict(list)
    for o in observations:
        clusters[o.signature].append(o)
    # Support = DISTINCT cases, not raw occurrences. A card re-surfaced N times
    # (reclassify passes, notification storms) is one data point, not N. When a
    # cluster carries no case identity (corpus registers), fall back to count.
    def _support(obs: list[Observation]) -> int:
        cases = {o.case for o in obs if o.case}
        return len(cases) if cases else len(obs)
    recurring = {sig: obs for sig, obs in clusters.items()
                 if _support(obs) >= spec.min_occurrences}
    # Attention budget: triage the loudest clusters first, cap per pass.
    # A pass is one model-call batch, not the whole backlog — the next pass
    # (after these proposals are applied) picks up the rest. Convergence over
    # passes, not within one.
    if len(recurring) > spec.max_clusters:
        recurring = dict(sorted(recurring.items(), key=lambda kv: -_support(kv[1]))
                         [:spec.max_clusters])

    summary = {
        "spec": spec.name,
        "goal": spec.goal,
        "observations": len(observations),
        "clusters": len(clusters),
        "recurring": len(recurring),
        "expert": [], "agent": [], "supervisor": [], "human": [],
        "replay_rejected": [], "cache_skipped": [],
        # verifier_down is an AVAILABILITY event, not a verdict — a flaky/timed-
        # out Sonnet call. Kept separate so a down verifier never reads as a
        # genuine idempotence rejection or a real escalation.
        "verifier_down": [],
    }

    if not recurring:
        if verbose:
            print(f"[{spec.name}] {len(observations)} obs, "
                  f"{len(clusters)} clusters, none recurring >= {spec.min_occurrences}")
        return summary

    history = spec.history()

    for sig, obs in sorted(recurring.items(), key=lambda kv: -len(kv[1])):
        ckey = _cluster_key(spec.name, sig)
        if ckey in rejects:  # cache stratum — don't re-propose a known reject
            summary["cache_skipped"].append(sig)
            continue

        # --- residue: Sonnet runs the four-case switch (postcondition enum) ---
        decision = _classify_cluster(spec, sig, obs)
        if decision is None:  # classifier down -> availability event, not a verdict
            summary["verifier_down"].append({"signature": sig, "stage": "classify",
                                             "support": _support(obs)})
            continue

        case = decision.get("case", "human")
        if case not in CASE_ENUM:  # enum wall — invented case -> human
            case = "human"

        # case == agent: irreducibly fuzzy, leave it in the nucleus.
        if case == "agent":
            summary["agent"].append({"signature": sig, "count": len(obs),
                                     "why": decision.get("rationale", "")})
            _log_residue(spec, sig, obs, decision)
            continue

        # case == human: can't tell if stable, escalate.
        if case == "human":
            summary["human"].append({"signature": sig, "count": len(obs),
                                     "reason": decision.get("rationale", "")})
            _emit_hitl_card(spec, sig, obs, case="human",
                            note=decision.get("rationale", ""))
            continue

        # case in {expert, supervisor}: stage a hoist, gated by the
        # idempotence wall. expert is the trivial/high-confidence rule;
        # supervisor is the constructed one. Both replay against history.
        replay = _replay_gate(spec, decision, history)
        if replay.get("unavailable"):  # verifier down -> don't cache as a reject
            summary["verifier_down"].append({"signature": sig, "stage": "replay",
                                             "support": _support(obs)})
            continue
        if not replay.get("clean", False):
            rejects[ckey] = {"signature": sig, "case": case,
                             "rejected_at": _now(),
                             "conflicts": replay.get("conflicts", [])}
            summary["replay_rejected"].append({"signature": sig, "case": case,
                                               "conflicts": replay.get("conflicts", [])})
            continue

        path = _write_proposal(spec, sig, obs, decision, replay)
        _emit_hitl_card(spec, sig, obs, case=case,
                        note=decision.get("proposal", ""), proposal_path=str(path))
        summary[case].append({"signature": sig, "count": len(obs),
                              "stratum": decision.get("stratum", ""),
                              "path": str(path)})

    _save_rejects(rejects)
    if verbose:
        print(json.dumps(summary, indent=2))
    return summary


# ---------------------------------------------------------------- residue prompts

def _classify_cluster(spec: SupervisorSpec, sig: str,
                      obs: list[Observation]) -> dict | None:
    system = (
        "You are a SUPERVISOR over a classifier actor in an automated PR "
        "pipeline. Your job is to encode expertise: move every STABLE "
        "distinction out of the model's prompt into a cheaper deterministic "
        "stratum, and leave only the irreducibly fuzzy in the model.\n\n"
        f"The actor's goal (your gradient): {spec.goal}\n\n"
        "You are shown a CLUSTER of recurring observations from the actor's "
        "attention channels (andon = the actor was confidently wrong and "
        "something tripped; inbox = the actor couldn't decide; corpus = a "
        "sample of how an expert handles this shape elsewhere; regret = the "
        "action the actor chose was later CONTRADICTED BY THE REAL OUTCOME — a "
        "caught SILENT misclassification, so the encoding should aim to flip "
        "the wrong action, not preserve it). Run a four-case switch, "
        "CHEAPEST-FIRST, and "
        "claim the cluster with the leftmost case that fits:\n"
        "  expert     — a stable distinction encodable as a TRIVIAL "
        "deterministic rule (no judgment, no edge cases). The cheapest hoist.\n"
        "  agent      — irreducibly fuzzy (hostile vs terse maintainer, which "
        "of two fixes is cleaner). Leave it in the LLM nucleus; encode nothing.\n"
        "  supervisor — stable, but the rule must be CONSTRUCTED carefully and "
        "could plausibly conflict with a past decision (needs replay-gating).\n"
        "  human      — you cannot tell whether the distinction is stable; "
        "do not guess. Escalate.\n\n"
        "Return JSON:\n"
        '{\n'
        '  "case": one of ["expert","agent","supervisor","human"],\n'
        '  "stratum": for expert/supervisor, one of '
        '["precondition","cache-key","cli-tool","postcondition"] '
        '(cheapest-first when several fit). Determinism clamps from both '
        'sides of the agent: precondition/postcondition wrap it from OUTSIDE; '
        'cli-tool goes INSIDE — a tool the agent calls so a fact it used to '
        'guess becomes deterministic ground truth while the agent keeps the '
        'judgment. Prefer cli-tool when the cluster is "model guessed a fact "'
        'it could have looked up",\n'
        '  "stratum_rationale": "why this stratum",\n'
        '  "proposal": "concrete artifact: the exact predicate/enum/CLI call/'
        'cache-key change, and roughly where it lives",\n'
        '  "predicate": "a one-line testable statement of the rule, phrased so '
        'it can be replayed against past decisions",\n'
        '  "rationale": "for agent/human: why it cannot be hoisted"\n'
        '}\n'
    )
    sample = "\n".join(f"- [{o.source}] {o.detail[:300]}" for o in obs[:12])
    user = (f"CLUSTER signature: {sig}\n"
            f"Occurrences: {len(obs)}\n\n"
            f"Sample observations:\n{sample}\n")
    return _ask_sonnet(system, user, spec.model)


def _replay_gate(spec: SupervisorSpec, decision: dict,
                 history: list[dict], *, sample: int = 50) -> dict:
    """The idempotence wall, with the agent BLINDED from the recorded action.

    A proposed hoist may ship only if it does NOT change any past decision the
    actor made. The naive check — hand the model the (before, action) pairs and
    ask "would R differ" — leaks the answer: the model rationalizes the recorded
    action instead of predicting it (the writer-naive-of-verifier failure). So
    instead we strip the action, show the model only the BEFORE-state, ask it to
    apply R and predict the bucket, then compare against the withheld action in
    Python. A held-out prediction, not a circular check.

    With no history to replay against (e.g. a public-corpus run on a fresh local
    substrate), the gate is vacuously clean but flagged untested."""
    predicate = decision.get("predicate", "")
    if not history:
        return {"clean": True, "conflicts": [], "untested": True,
                "note": "no local decision history to replay against"}

    # Blind: the model sees {id, input} only. The actual action stays in
    # Python, never crosses into the prompt.
    blinded: list[dict] = []
    actual: dict[int, str] = {}
    for i, row in enumerate(history[:sample]):
        blinded.append({"id": i, "before": row.get("input")})
        actual[i] = str(row.get("bucket"))

    system = (
        "You apply a proposed DETERMINISTIC RULE R to historical cases. You "
        "are shown ONLY the before-state of each case — NOT the action that "
        "was actually taken. Do not guess the historical action; apply R "
        "mechanically. For each case: if R's antecedent matches the "
        "before-state, return the bucket R would force; if R does not apply "
        "to that case, return null. Return JSON: "
        '{"verdicts": {"<id>": "<bucket-or-null>", ...}}'
    )
    user = (f"Rule R: {predicate}\n"
            f"Proposal detail: {decision.get('proposal', '')}\n\n"
            f"Cases (before-state only):\n{json.dumps(blinded, default=str)[:7000]}")
    out = _ask_sonnet(system, user, spec.model)
    if out is None:  # can't verify -> fail closed, but flag as availability event
        return {"clean": False, "conflicts": [], "unavailable": True,
                "note": "replay verifier unavailable; failing closed"}

    # Compare the blinded predictions against the withheld actions, in Python.
    verdicts = out.get("verdicts", {}) if isinstance(out, dict) else {}
    conflicts: list[dict] = []
    applied = 0
    for sid, predicted in verdicts.items():
        try:
            i = int(sid)
        except (TypeError, ValueError):
            continue
        if predicted in (None, "", "null", "None"):
            continue  # R doesn't apply -> no conflict (it only adds a branch)
        applied += 1
        was = actual.get(i)
        if was is not None and str(predicted) != was:
            conflicts.append({"id": i, "before": blinded[i]["before"],
                              "was": was, "would_be": predicted})
    return {"clean": not conflicts, "conflicts": conflicts,
            "cases": len(blinded), "applied": applied, "blinded": True}


# ---------------------------------------------------------------- emit

def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _write_proposal(spec: SupervisorSpec, sig: str, obs: list[Observation],
                    decision: dict, replay: dict) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", sig.lower()).strip("-")[:48] or "unnamed"
    path = PROPOSALS_DIR / f"{spec.name}__{slug}.md"
    evidence = "\n".join(f"- [{o.source}] {o.detail[:400]}" for o in obs[:15])
    untested = replay.get("untested")
    body = f"""---
spec: {spec.name}
case: {decision.get('case')}
stratum: {decision.get('stratum', '')}
occurrences: {len(obs)}
created: {_now()}
status: proposed
replay_clean: {replay.get('clean')}
replay_untested: {bool(untested)}
---

# Supervisor proposal — {spec.name}: {decision.get('case')} / {decision.get('stratum', '')}

**Goal (gradient):** {spec.goal}

**Cluster signature:** `{sig}`  ({len(obs)} occurrences)

## Proposed artifact
{decision.get('proposal', '(none)')}

**Predicate (replayable):** {decision.get('predicate', '(none)')}

**Why this stratum:** {decision.get('stratum_rationale', '(none)')}

## Replay against history (idempotence wall)
- clean: {replay.get('clean')}
- {"UNTESTED — " + replay.get('note', '') if untested else "conflicts: " + json.dumps(replay.get('conflicts', []))}

## Evidence
{evidence}

---
*Propose-only. To apply: review the predicate, write the edit, then archive this file.*
"""
    path.write_text(body)
    return path


def _emit_hitl_card(spec: SupervisorSpec, sig: str, obs: list[Observation],
                    *, case: str, note: str, proposal_path: str | None = None) -> None:
    """One card on the operator's human inbox. `human`-case clusters land here
    for disambiguation; expert/supervisor proposals land here as an approval
    request. Both are withdrawals from the human-attention account, so each
    must point at a durable change (the proposal file) or a narrow question."""
    from sweep.types import Message
    ts = dt.datetime.now(dt.timezone.utc)
    payload = {
        "supervisor_spec": spec.name,
        "case": case,
        "signature": sig,
        "occurrences": len(obs),
        "note": note[:600],
    }
    if proposal_path:
        payload["proposal_path"] = proposal_path
        payload["summary"] = (f"supervisor[{spec.name}]: proposed {case} hoist "
                              f"for {len(obs)}x '{sig}' — review {proposal_path}")
    else:
        payload["summary"] = (f"supervisor[{spec.name}]: human-case cluster "
                              f"{len(obs)}x '{sig}' — {note[:120]}")
    msg = Message(
        msg_id=f"human-supervisor-{spec.name}-{_cluster_key(spec.name, sig)}",
        sender="supervisor",
        intent="encode" if proposal_path else "disambiguate",
        payload=payload,
        ts=ts.isoformat(),
        ledger=[],
    )
    HUMAN_INBOX.parent.mkdir(parents=True, exist_ok=True)
    with open(HUMAN_INBOX, "a") as f:
        f.write(json.dumps(asdict(msg)) + "\n")


def _log_residue(spec: SupervisorSpec, sig: str, obs: list[Observation],
                 decision: dict) -> None:
    """llm-shaped clusters are the residue — what the nucleus must keep. We
    don't surface them to the operator (nothing to encode), but we record
    them so a later pass can confirm the residue is stable, not just
    under-encoded."""
    RESIDUE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(RESIDUE_LOG, "a") as f:
        f.write(json.dumps({
            "ts": _now(), "spec": spec.name, "signature": sig,
            "occurrences": len(obs), "rationale": decision.get("rationale", ""),
        }) + "\n")


# ---------------------------------------------------------------- actor shape

async def supervisor_cycle(msg) -> dict:
    """Actor-shaped entrypoint — Message in, dict out, same contract as every
    other *_cycle. Deliberately NOT decorated with @activity.defn and NOT
    registered on the worker: the supervisor runs standalone today. When live
    data is wanted, decorate this, register it, and kick it from the metronome
    like retro — no other change needed. The Message's payload names the spec
    (`{"spec": "switch"}`); the spec registry is resolved lazily so this module
    has no import-time dependency on the (gh/jsonl-heavy) specs module."""
    from sweep.supervisor_specs import (SPECS, contributor_spec,
                                        review_action_spec, author_response_spec)
    name = (getattr(msg, "payload", {}) or {}).get("spec", "switch")
    spec = SPECS.get(name)
    if spec is None and name.startswith("actions-"):
        spec = review_action_spec(name[len("actions-"):])
    if spec is None and name.startswith("respond-"):
        spec = author_response_spec(name[len("respond-"):])
    if spec is None and name.startswith("corpus-"):
        spec = contributor_spec(name[len("corpus-"):])
    if spec is None:
        return {"error": f"unknown supervisor spec: {name}"}
    return supervise(spec)
