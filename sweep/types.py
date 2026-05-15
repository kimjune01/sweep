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
    the receipts — the gate verifier re-hashes the artifact to detect forgery."""

    verdict: Verdict
    artifact_path: str  # where the raw response was captured
    sha256: str
    rounds: int = 1
    verbatim_excerpt: str = ""  # must substring-match contents of artifact_path
    provenance: str = ""  # e.g. "codex" or "opus-fallback"


@dataclass
class QaOneEntryRequest:
    msg_id: str
    repo: str  # exactly one
    branch: str  # exactly one
    worktree: str
    test_cmd: str
    issue: int | None = None


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
