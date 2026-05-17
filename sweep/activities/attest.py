"""Attest — behavioral verification, split out of qa.

Runs the test-attestation gate (fail-on-master, pass-on-fix) and routes
the card based on outcome:

  pass         → qa.jsonl (with attestation_hash payload; qa skips its
                 own internal test_attestation and only does adversarial
                 review)
  fail, 1st    → investigate.jsonl (one cheap retry)
  fail, 2nd+   → human.jsonl (escalation)

"1st vs 2nd" is read from the kanban trail: `msg.path.count("attest")`.
First time attest sees a card, path has no "attest"; second time, it
does. No separate counter, no cross-inbox reads.

Pre/post matches qa: the attestation artifact lands on disk via the
same `_capture()` path qa already uses, and the routed message carries
`attestation_hash` so downstream actors can hydrate the GateAttestation
from disk without re-running tests.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict
from pathlib import Path

from temporalio import activity
from temporalio.exceptions import ApplicationError

from sweep.types import Message, QaOneEntryRequest


ATTEST_INBOX = Path.home() / ".sweep" / "inbox" / "attest.jsonl"
HUMAN_INBOX = Path.home() / ".sweep" / "inbox" / "human.jsonl"
QA_INBOX = Path.home() / ".sweep" / "inbox" / "qa.jsonl"
INVESTIGATE_INBOX = Path.home() / ".sweep" / "inbox" / "investigate.jsonl"


def _append(inbox: Path, msg: Message) -> None:
    inbox.parent.mkdir(parents=True, exist_ok=True)
    with open(inbox, "a") as f:
        f.write(json.dumps(asdict(msg)) + "\n")


@activity.defn
async def kick_attest_card(repo: str, branch: str,
                           pr: int | None = None,
                           sender: str = "investigate",
                           incoming_path: list[str] | None = None,
                           payload: dict | None = None) -> str | None:
    """Deposit an attest card on attest.jsonl and signal attest-actor.

    Caller should pass `incoming_path = incoming.path + [incoming.sender]`
    when forwarding. Origin callers (pr-state) pass [].
    """
    from sweep import observe
    from sweep.activities.pr_state import _signal_actor

    ts = dt.datetime.now(dt.timezone.utc)
    slug = repo.replace("/", "-")
    suffix = f"-{pr}" if pr else f"-{branch}"
    msg_id = f"attest-{ts.strftime('%Y%m%dT%H%M%S')}-{slug}{suffix}"
    msg = Message(
        msg_id=msg_id,
        sender=sender,
        intent="attest",
        repo=repo,
        pr=pr,
        branch=branch,
        payload=payload or {},
        ts=ts.isoformat(),
        path=incoming_path or [],
    )
    try:
        _append(ATTEST_INBOX, msg)
    except Exception as e:
        observe.event("attest_card_write_failed", repo=repo, branch=branch,
                      error_type=type(e).__name__, error=str(e)[:200])
        return None
    observe.event("attest_card_deposited", repo=repo, branch=branch,
                  sender=sender, msg_id=msg_id)
    return await _signal_actor("attest", msg)


def _forward_path(msg: Message) -> list[str]:
    """Path to stamp on a card we're about to emit downstream."""
    return list(msg.path) + [msg.sender]


def _emit(inbox: Path, msg: Message, *, kind: str, extra_payload: dict) -> Message:
    """Forward a card downstream. msg_id is derived deterministically
    from the incoming msg_id so Temporal retries don't double-deposit
    (the receiver dedupes on msg_id; deterministic keys keep idempotency
    intact across activity retries)."""
    out = Message(
        msg_id=f"{kind}-from-{msg.msg_id}",
        sender="attest",
        intent=f"{kind}-after-attest",
        repo=msg.repo,
        pr=msg.pr,
        branch=msg.branch,
        payload={**(msg.payload or {}), **extra_payload},
        ts=dt.datetime.now(dt.timezone.utc).isoformat(),
        path=_forward_path(msg),
    )
    _append(inbox, out)
    return out


def _route_pass(msg: Message, attestation_hash: str) -> Message:
    return _emit(QA_INBOX, msg, kind="qa",
                 extra_payload={"attestation_hash": attestation_hash})


def _route_retry(msg: Message, reason: str) -> Message:
    return _emit(INVESTIGATE_INBOX, msg, kind="investigate",
                 extra_payload={"attest_failure_reason": reason[:500]})


def _route_human(msg: Message, reason: str) -> Message:
    return _emit(HUMAN_INBOX, msg, kind="human",
                 extra_payload={"attest_failure_reason": reason[:500]})


@activity.defn
async def attest_cycle(msg: Message) -> dict:
    """Run test_attestation; route by verdict + kanban position.

    Halts (andon) only on broken substrate — missing toolchain, git
    failures, test_passes_on_master (bug fixed upstream). Genuine
    fail-on-fix is a routable outcome, not a halt.
    """
    from sweep import observe
    from sweep.activities.qa import test_attestation
    from sweep.activities.worktree import ensure_worktree
    from sweep.activities.infer import infer_test_cmd

    if not msg.repo or not msg.branch:
        raise ApplicationError(
            "attest: msg.repo and msg.branch required", non_retryable=True,
        )

    worktree = await ensure_worktree(msg.repo, msg.branch)
    test_cmd = await infer_test_cmd(worktree, msg.repo)
    req = QaOneEntryRequest(
        msg_id=msg.msg_id,
        repo=msg.repo,
        branch=msg.branch,
        worktree=worktree,
        test_cmd=test_cmd,
        issue=int(msg.pr) if msg.pr else 0,
    )

    second_look = msg.path.count("attest") >= 1

    try:
        att = await test_attestation(req)
    except ApplicationError as e:
        reason = str(e.message or "")
        # "test_fails_on_fix" is a genuine, routable verdict, not
        # broken substrate. Everything else (toolchain missing, master
        # passing, git checkout failure) propagates to halt the actor.
        if "test_fails_on_fix" not in reason:
            raise

        target = "human" if second_look else "investigate"
        if second_look:
            _route_human(msg, reason)
        else:
            _route_retry(msg, reason)
        observe.event(
            "attest_routed", repo=msg.repo, branch=msg.branch,
            verdict="fail", target=target, second_look=second_look,
            msg_id=msg.msg_id,
        )
        return {
            "verdict": "fail",
            "target": target,
            "second_look": second_look,
            "msg_id": msg.msg_id,
        }

    _route_pass(msg, attestation_hash=att.sha256)
    observe.event(
        "attest_routed", repo=msg.repo, branch=msg.branch,
        verdict="pass", target="qa", attestation_hash=att.sha256,
        msg_id=msg.msg_id,
    )
    return {
        "verdict": "pass",
        "target": "qa",
        "attestation_hash": att.sha256,
        "msg_id": msg.msg_id,
    }
