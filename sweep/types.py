"""Shared dataclasses for the sweep pipeline.

The OTP-shaped contract lives in these types: every activity input/output is
structured, every msg_id is required, every gate attestation is typed. The
type signatures are the WIP=1 and idempotence enforcement we used to scribble
in skill prose.

Intentionally no `from __future__ import annotations`: temporal's payload
converter resolves dataclass field type hints at activity-result decode
time via `get_type_hints`, and stringified forward refs to module-level
aliases like `Bucket = Literal[...]` don't survive that resolution inside
the workflow sandbox.
"""

from dataclasses import dataclass, field
from typing import Literal


# ---------------------------------------------------------------- envelopes


@dataclass
class Message:
    """One unit of work delivered to an actor. msg_id is deterministic on the
    sender side so re-delivery is idempotent."""

    msg_id: str
    sender: str  # e.g. "remit"
    intent: str  # e.g. "reattest", "respond", "close", "publish", "rebase"
    repo: str | None = None  # owner/repo; None for repo-agnostic cards (rope kicks, leakdog heartbeats)
    pr: int | None = None
    branch: str | None = None
    payload: dict = field(default_factory=dict)
    ts: str = ""  # ISO 8601 UTC
    # The card's own ledger of where it's been. Each actor that
    # forwards the card appends the previous sender (the actor it
    # came from). Receivers count their own name in the ledger to
    # answer "is this my Nth look?" — that's how attest decides
    # between "bounce back to investigate" (1st fail) and "escalate
    # to human" (2nd fail).
    # Default [] for origin cards (pr-state from gh, scout, operator).
    # Always set via forward_ledger() — never compute by hand.
    ledger: list[str] = field(default_factory=list)


def forward_ledger(incoming: "Message | None") -> list[str]:
    """The ledger to stamp on a new card emitted from inside an
    activity that's processing `incoming`. Origin sites (pr-state from
    gh, scout heartbeats, operator kicks) pass None → []. Every
    kick_*_card helper accepts an `incoming` param and routes it
    through here so there's exactly one way to extend the ledger.

    Temporal's data converter can hand us either a Message dataclass
    or a plain dict (when the activity signature only loosely typed
    `incoming`, or when crossing certain serialization paths). Handle
    both so the ledger doesn't break on the path that does the dict
    form — the cost is two attr-vs-key reads, the benefit is no class
    of silent ledger truncation."""
    if incoming is None:
        return []
    if isinstance(incoming, dict):
        return list(incoming.get("ledger") or []) + [incoming.get("sender") or ""]
    return list(incoming.ledger) + [incoming.sender]


# ---------------------------------------------------------------- qa types


Verdict = Literal["pass", "fail", "revise", "stubbed"]


@dataclass
class GateAttestation:
    """A single reviewer's attestation. The `artifact_path` and `sha256` are
    the receipts — the gate verifier re-hashes the artifact to detect forgery.

    Event-pinned fuses (populated per attestation kind, None when irrelevant):
    each gate pins itself to a specific value of the world. The fuse blows
    when that value changes — wall-clock time has nothing to do with it.
    """

    verdict: Verdict
    artifact_path: str  # where the raw response was captured
    sha256: str
    rounds: int = 1
    verbatim_excerpt: str = ""  # must substring-match contents of artifact_path
    provenance: str = ""  # e.g. "codex" or "opus-fallback"
    # Fuse pins — set the ones relevant to this attestation kind.
    pinned_head_sha: str | None = None         # qa gates: invalid if PR head moves
    pinned_base_sha: str | None = None         # rebase status: invalid if base advances
    pinned_latest_review_id: str | None = None  # review classification: invalid if newer review arrives


@dataclass
class QaOneEntryRequest:
    msg_id: str
    repo: str  # exactly one
    branch: str  # exactly one
    worktree: str
    test_cmd: str
    issue: int | None = None


Bucket = Literal["close", "human", "rebase", "qa", "reqa", "investigate",
                 "reinvestigate", "done", "wait"]

# Each bucket has a destination inbox + intent verb the receiver consumes.
#
# Two parallel lanes share the /investigate and /qa skills but have
# different upstreams, downstreams, and entry preconditions:
#
#   production:  triaged → investigate   → qa   → compose → submit → respond
#   engagement:  remit   → reinvestigate → reqa →                    respond
#
# investigate/qa enforce msg.pr=None (new-issue); reinvestigate/reqa
# enforce msg.pr presence (engagement-lane only). The split removes the
# qa→{compose,respond} conditional at the cost of two extra workflow
# IDs and inboxes that share their underlying skill code.
#
# Two distinct no-action shapes:
#   - "done"  (APPROVED + MERGEABLE + green CI): maintainer's court.
#             We don't merge. No actor, no audit — ack and forget.
#             NotificationPoller will see a state change if the maintainer
#             acts; until then, the PR is *out* of our routing rotation.
#   - "wait"  (no action signal yet): keep watching. Routes to retro for
#             periodic audit — wait is an action because it polls and
#             routes; done is not.
BUCKET_ROUTING: dict[str, tuple[str, str]] = {
    "close":         ("respond",       "close"),
    "human":         ("human",         "respond"),
    "rebase":        ("respond",       "rebase"),
    "qa":            ("qa",            "review"),
    "reqa":          ("reqa",          "reattest-followup"),
    "investigate":   ("investigate",   "diagnose"),
    "reinvestigate": ("reinvestigate", "diagnose-followup"),
    "wait":          ("retro_audit",   "audit"),
}


@dataclass
class PrLiveState:
    """Live state of a PR pulled from gh.

    `state` is OPEN / CLOSED / MERGED. The classifier short-circuits
    non-OPEN PRs to the `done` bucket — they're terminal regardless of
    review/CI signals (a CLOSED PR with failing CI doesn't need
    reinvestigation; it needs forgetting).
    """

    repo: str
    pr: int
    branch: str
    title: str
    url: str
    state: str  # OPEN / CLOSED / MERGED
    review_decision: str  # APPROVED / CHANGES_REQUESTED / REVIEW_REQUIRED / ""
    mergeable: str  # MERGEABLE / CONFLICTING / UNKNOWN / ""
    ci: str  # green / failing / pending / unknown
    activity_h: float  # hours since updatedAt
    maintainer_question: bool
    is_draft: bool
    failing_check: str = ""  # name of one failing check, for reason
    # maintainer_raised_concern: maintainer flagged a NEW bug/issue in an
    # in-PR comment that the author hasn't addressed. Different from
    # maintainer_question (which is "you owe an answer"); this is "we owe
    # another investigation pass." Routes to investigate, not human.
    maintainer_raised_concern: bool = False
    # A MEMBER/OWNER submitted an APPROVED review *after* the latest
    # outstanding CHANGES_REQUESTED. GitHub's `reviewDecision` aggregate
    # stays at CHANGES_REQUESTED until the earlier review is dismissed,
    # so the classifier needs this side-channel to recognize that the
    # PR is effectively approved by someone with merge rights.
    member_approved_over_cr: bool = False


@dataclass
class PrStateResult:
    repo: str
    pr: int
    branch: str
    bucket: Bucket
    signals: dict
    reason: str
    is_draft: bool = False


@dataclass
class QaOneEntryResult:
    msg_id: str
    verdict: Literal["pass", "fail", "partial"]
    bugs_found: int  # int (incl. 0) — tick.py demoter checks isinstance int
    test_attestation: GateAttestation
    codex: GateAttestation
    gemini_first: GateAttestation
    gemini_last: GateAttestation
    elapsed_seconds: float
    reason: str = ""
