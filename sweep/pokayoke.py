"""Poka-yoke: shared inbox-boundary intake checks.

Toyota's poka-yoke — error-proofing — applied at every actor's inbox
edge. Pattern-matched message contracts: wrong-shape input can't enter
the next stage. One module of pure functions, every actor pre-validates
the same way.

Each check is a function `(msg-or-fields) → SkipReason | None`. The
function answers "should this card enter the actor?" with either None
(pass) or a structured reason (reject). Composition is just a list of
checks; the first one to return a Reason wins.

Why pure functions: actors live across processes / restarts / threads.
Sharing state would couple them. Sharing the validation logic doesn't.

Why structured Reason (not bool): the rejected-as-third-outcome
trichotomy (decided | errored | rejected) only works if rejections
carry their cause forward. The Reason.code becomes the observe event
field, the sink row reason, and the remediation-prompt classifier
input — single source of truth for the wrong-shape diagnosis.

Phased migration: the module is added first with no callers, then each
actor switches over one at a time. The existing scattered checks
(`is_repo_evicted` in qa.py, the inline draft check in attest_cycle,
compose's attestation_hash precondition) will pull through this module
once the bulk dump settles.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


@dataclass(frozen=True)
class SkipReason:
    """Structured rejection. The `code` is the stable identifier (used
    in events, sink rows, remediation-prompt matching); `detail` is
    human-readable context."""
    code: str
    detail: str


# ── primitives ──────────────────────────────────────────────────────


def is_repo_evicted(repo: str) -> SkipReason | None:
    """Repo on the operator's evict list (sift_evicted.txt) or kill
    list (sift_kill_list.txt). Either marks the repo out-of-rotation
    — no actor should process its cards."""
    if not repo:
        return None
    from sweep.activities.sift import _on_evicted_list, _on_kill_list
    if _on_evicted_list(repo):
        return SkipReason("repo_evicted", f"{repo} on sift_evicted.txt")
    if _on_kill_list(repo):
        return SkipReason("repo_killed", f"{repo} on sift_kill_list.txt")
    return None


def is_pr_draft(repo: str, pr: int | None) -> SkipReason | None:
    """PR in draft state on GitHub. Operator-parked; substrate should
    not touch the body or push receipts."""
    if not repo or not pr:
        return None
    from sweep import gh_io
    try:
        d = gh_io.pr_view(repo, int(pr), fields="isDraft", ttl=60)
    except Exception:
        return None  # fail-open: don't block on transient gh errors
    if d.get("isDraft"):
        return SkipReason("pr_is_draft", f"{repo}#{pr} is draft")
    return None


def is_pr_closed_or_merged(repo: str, pr: int | None) -> SkipReason | None:
    """PR is terminal — closed or merged. Out of rotation regardless
    of branch state."""
    if not repo or not pr:
        return None
    from sweep import gh_io
    try:
        d = gh_io.pr_view(repo, int(pr), fields="state", ttl=60)
    except Exception:
        return None
    state = (d.get("state") or "").upper()
    if state in ("CLOSED", "MERGED"):
        return SkipReason(
            f"pr_{state.lower()}", f"{repo}#{pr} state={state}"
        )
    return None


def is_pr_approved(repo: str, pr: int | None) -> SkipReason | None:
    """PR is approved by a maintainer (literal `reviewDecision=APPROVED`
    OR member-approved-over-CR shape). Maintainer's court — no further
    substrate action."""
    if not repo or not pr:
        return None
    from sweep import gh_io
    try:
        d = gh_io.pr_view(
            repo, int(pr),
            fields="reviewDecision,reviews,author",
            ttl=60,
        )
    except Exception:
        return None
    if d.get("reviewDecision") == "APPROVED":
        return SkipReason("pr_approved", f"{repo}#{pr} reviewDecision=APPROVED")
    # member_approved_over_cr — a MEMBER/OWNER approved after the
    # latest non-author CHANGES_REQUESTED. GH's aggregate stays at
    # CHANGES_REQUESTED until the older review is dismissed; this is
    # the real "approved" signal for that case.
    author = (d.get("author") or {}).get("login") or ""
    from sweep.activities.pr_state import _member_approved_over_cr
    if _member_approved_over_cr(d.get("reviews") or [], author_login=author):
        return SkipReason(
            "pr_member_approved_over_cr",
            f"{repo}#{pr} member approved over outstanding CR",
        )
    return None


def has_attestation_hash(payload: dict | None) -> SkipReason | None:
    """Card lacks attestation_hash on payload. compose's hard
    precondition — without it the upstream wiring is broken
    (somebody routed past attest)."""
    if not (payload or {}).get("attestation_hash"):
        return SkipReason(
            "missing_attestation_hash",
            "payload has no attestation_hash; upstream did not route through attest",
        )
    return None


def is_pr_in_sink(repo: str, pr: int | None) -> SkipReason | None:
    """The (repo, pr) pair appears in sink.jsonl — operator has
    already disposed of this PR. Skip rather than re-process."""
    if not repo or not pr:
        return None
    sink = Path.home() / ".sweep" / "inbox" / "sink.jsonl"
    if not sink.exists():
        return None
    try:
        for line in sink.read_text().splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("repo") == repo and row.get("pr") == int(pr):
                return SkipReason(
                    "pr_in_sink",
                    f"{repo}#{pr} previously sunk: {row.get('reason', '?')[:120]}",
                )
    except OSError:
        return None
    return None


# ── composition ─────────────────────────────────────────────────────


# A `Check` is anything callable that returns `SkipReason | None` when
# invoked with the right shape. Callers compose them as lambdas over
# the msg fields the check needs.
Check = Callable[[], "SkipReason | None"]


def first_skip(checks: Iterable[Check]) -> SkipReason | None:
    """Run checks in order, return the first SkipReason or None.
    Short-circuits — later checks don't run after a reject."""
    for c in checks:
        r = c()
        if r is not None:
            return r
    return None


# ── per-actor intake compositions ───────────────────────────────────
#
# Each helper takes the actor's message-shape and returns SkipReason
# or None. Activities call these at entry and short-circuit on reject.


def attest_intake(msg) -> SkipReason | None:
    """Checks at attest_cycle entry."""
    return first_skip([
        lambda: is_repo_evicted(msg.repo),
        lambda: is_pr_in_sink(msg.repo, msg.pr),
        lambda: is_pr_draft(msg.repo, msg.pr),
        lambda: is_pr_closed_or_merged(msg.repo, msg.pr),
        lambda: is_pr_approved(msg.repo, msg.pr),
    ])


def compose_intake(msg) -> SkipReason | None:
    """Checks at compose_cycle entry. attestation_hash is the
    load-bearing precondition; the rest catch cards that shouldn't
    even reach here."""
    return first_skip([
        lambda: is_repo_evicted(msg.repo),
        lambda: is_pr_closed_or_merged(msg.repo, msg.pr),
        lambda: has_attestation_hash(msg.payload),
    ])


def qa_intake(msg) -> SkipReason | None:
    """Checks at QaActor _process_one entry."""
    return first_skip([
        lambda: is_repo_evicted(msg.repo),
        lambda: is_pr_in_sink(msg.repo, msg.pr),
        lambda: is_pr_draft(msg.repo, msg.pr),
        lambda: is_pr_closed_or_merged(msg.repo, msg.pr),
        lambda: is_pr_approved(msg.repo, msg.pr),
    ])


def amend_intake(msg) -> SkipReason | None:
    """Checks at amend_cycle entry. amend writes to PR bodies, so
    closed/merged PRs are particularly important to skip — the body
    edit on a closed PR is loud and useless."""
    return first_skip([
        lambda: is_repo_evicted(msg.repo),
        lambda: is_pr_closed_or_merged(msg.repo, msg.pr),
        lambda: is_pr_draft(msg.repo, msg.pr),
    ])


def reqa_intake(msg) -> SkipReason | None:
    return first_skip([
        lambda: is_repo_evicted(msg.repo),
        lambda: is_pr_closed_or_merged(msg.repo, msg.pr),
        lambda: is_pr_approved(msg.repo, msg.pr),
    ])


def reinvestigate_intake(msg) -> SkipReason | None:
    return first_skip([
        lambda: is_repo_evicted(msg.repo),
        lambda: is_pr_in_sink(msg.repo, msg.pr),
        lambda: is_pr_closed_or_merged(msg.repo, msg.pr),
        lambda: is_pr_approved(msg.repo, msg.pr),
    ])
