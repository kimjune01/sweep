"""Shared dataclasses for the sweep pipeline.

The OTP-shaped contract lives in these types: every activity input/output is
structured, every msg_id is required, every gate attestation is typed. The
type signatures are the WIP=1 and idempotence enforcement we used to scribble
in skill prose.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


# ---------------------------------------------------------------- envelopes


@dataclass
class Message:
    """One unit of work delivered to an actor. msg_id is deterministic on the
    sender side so re-delivery is idempotent."""

    msg_id: str
    sender: str  # e.g. "pr-state"
    intent: str  # e.g. "reattest", "respond", "close", "ship", "rebase"
    repo: str  # owner/repo
    pr: int | None = None
    branch: str | None = None
    payload: dict = field(default_factory=dict)
    ts: str = ""  # ISO 8601 UTC


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


Bucket = Literal["close", "respondable", "rebase", "qa", "ship", "wait"]

# Each bucket has a destination inbox + intent verb the receiver consumes.
#
# Note: pr-state classifies *existing* open PRs. When a reviewer engages
# (comment, changes_requested), the ball comes back to the human — that's
# "respondable," not "investigate." The investigate.jsonl inbox is reserved
# for /triage and /actionable to populate with new-issue work for the LLM
# investigator actor.
BUCKET_ROUTING: dict[str, tuple[str, str]] = {
    "close":       ("drip",        "close"),
    "respondable": ("respondable", "respond"),
    "rebase":      ("drip",        "rebase"),
    "qa":          ("qa",          "reattest"),
    "ship":        ("drip",        "ship"),
    "wait":        ("retro",       "audit"),
}


@dataclass
class PrLiveState:
    """Live state of an open PR pulled from gh."""

    repo: str
    pr: int
    branch: str
    title: str
    url: str
    review_decision: str  # APPROVED / CHANGES_REQUESTED / REVIEW_REQUIRED / ""
    mergeable: str  # MERGEABLE / CONFLICTING / UNKNOWN / ""
    ci: str  # green / failing / pending / unknown
    activity_h: float  # hours since updatedAt
    maintainer_question: bool
    is_draft: bool
    failing_check: str = ""  # name of one failing check, for reason


@dataclass
class PrStateResult:
    repo: str
    pr: int
    branch: str
    bucket: Bucket
    signals: dict
    reason: str


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
