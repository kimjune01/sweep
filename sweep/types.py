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


Bucket = Literal["close", "human", "rebase", "qa", "investigate", "done", "wait"]

# Each bucket has a destination inbox + intent verb the receiver consumes.
#
# Note: remit classifies *existing* open PRs. When a reviewer engages
# (comment, changes_requested), the ball comes back to the human — that's
# the "human" bucket, not "investigate." The investigate.jsonl inbox is
# reserved for /triage and /actionable to populate with new-issue work
# for the LLM investigator actor — plus the maintainer-raised-concern
# path from remit (a new in-PR bug routes to investigate, not human).
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
    "close":       ("respond",     "close"),
    "human":       ("human",       "respond"),
    "rebase":      ("respond",     "rebase"),
    "qa":          ("qa",          "reattest"),
    "investigate": ("investigate", "diagnose"),
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
    # maintainer_raised_concern: maintainer flagged a NEW bug/issue in an
    # in-PR comment that the author hasn't addressed. Different from
    # maintainer_question (which is "you owe an answer"); this is "we owe
    # another investigation pass." Routes to investigate, not human.
    maintainer_raised_concern: bool = False


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
