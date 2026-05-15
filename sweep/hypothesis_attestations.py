"""Hypothesis attestations — per-PR classification against the meta
hypothesis graph (H0..HN).

HOLLOW. The store, schema, and verbs (supports/refutes vs bears-on vs
orthogonal) are deliberately unspecified. Earned when prose
classification in ~/.sweep/HYPOTHESIS_GRAPH.md stops scaling — first
time you try to query the prose and can't.

Distinct from `attestations.py` (LLM-call provenance, hash-chained).
This file is PR-outcome → hypothesis mapping.
"""

from __future__ import annotations


# TODO: storage. JSONL at ~/.sweep/hypothesis_attestations.jsonl is the
# obvious first cut. Defer until the prose form breaks.

# TODO: schema. Candidate fields: repo, number, outcome, supports[],
# refutes[], closed_at, note, ts. Verbs may shift once real
# classification load arrives — don't lock in advance.

# TODO: readers — for_pr, support(H), refute(H), hypothesis_summary().
# Each is a join against outcomes.recent_records on (repo, number).

# TODO: writer — wire from /retro skill at the moment a human classifies
# a cycle's outcomes. Until then, classification lives in prose.


def record(*args, **kwargs) -> None:
    """No-op. See module docstring."""
    return None


def for_pr(repo: str, number: int) -> None:
    """No-op. See module docstring."""
    return None


def support(h: str) -> list:
    """No-op. See module docstring."""
    return []


def refute(h: str) -> list:
    """No-op. See module docstring."""
    return []


def hypothesis_summary() -> dict:
    """No-op. See module docstring."""
    return {}
