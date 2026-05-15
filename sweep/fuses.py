"""Event-pinned fuses for attestations.

Each gate pins itself to a value of the world (PR head SHA, base SHA,
latest review ID). The fuse blows when the world's current value diverges
from the pinned one — independent of wall-clock time. A 30-second-old
attestation can be valid forever on a dormant repo and stale immediately
on an active one.

Usage:

    blown, reason = fuses.check_qa_gate(att, current_head_sha="abc123...")
    if blown:
        raise ApplicationError(f"stale qa attestation: {reason}",
                               non_retryable=True)

Helpers are pure functions of (attestation, current_value). No I/O — the
caller fetches current values from gh_io and passes them in. Keeps the
check trivially testable.
"""

from __future__ import annotations

from sweep.types import GateAttestation


def check_head_sha(att: GateAttestation, current_head_sha: str) -> tuple[bool, str]:
    """qa gates: stale if PR head SHA moved since attestation."""
    if att.pinned_head_sha is None:
        return False, "no head-sha pin (attestation not bound to a SHA)"
    if att.pinned_head_sha != current_head_sha:
        return True, (
            f"head SHA changed: pinned {att.pinned_head_sha[:12]} "
            f"vs current {current_head_sha[:12]}"
        )
    return False, "head SHA matches"


def check_base_sha(att: GateAttestation, current_base_sha: str) -> tuple[bool, str]:
    """rebase-status gates: stale if base branch advanced."""
    if att.pinned_base_sha is None:
        return False, "no base-sha pin"
    if att.pinned_base_sha != current_base_sha:
        return True, (
            f"base SHA advanced: pinned {att.pinned_base_sha[:12]} "
            f"vs current {current_base_sha[:12]}"
        )
    return False, "base SHA matches"


def check_review_id(att: GateAttestation, latest_review_id: str | None) -> tuple[bool, str]:
    """review-classification gates: stale if a newer review arrived."""
    if att.pinned_latest_review_id is None:
        return False, "no review-id pin"
    if latest_review_id != att.pinned_latest_review_id:
        return True, (
            f"newer review since classification: pinned "
            f"{att.pinned_latest_review_id} vs current {latest_review_id}"
        )
    return False, "latest review id matches"


def check_qa_bundle(
    test_att: GateAttestation,
    codex_att: GateAttestation,
    gemini_first: GateAttestation,
    gemini_last: GateAttestation,
    *,
    current_head_sha: str,
) -> tuple[bool, list[str]]:
    """All four qa gates share the same fuse (PR head SHA). Returns
    (any_blown, list_of_reasons_per_gate). Use this at ship time."""
    reasons: list[str] = []
    any_blown = False
    for name, att in [
        ("test_attestation", test_att),
        ("codex", codex_att),
        ("gemini_first", gemini_first),
        ("gemini_last", gemini_last),
    ]:
        blown, why = check_head_sha(att, current_head_sha)
        reasons.append(f"{name}: {why}")
        if blown:
            any_blown = True
    return any_blown, reasons
