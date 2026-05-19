"""Amend — idempotent PR-description editor.

Splices marker-wrapped blocks into the PR body. Each block is keyed by
`payload.kind`; the marker pair lets re-runs replace the prior block
in-place instead of appending duplicates.

Today only one kind is wired: `"attestation"` — appends the triple-link
footer rendered upstream by qa's test_attestation step (carried on
`payload.attestation_links_md`). Future kinds (screenshots, sections)
plug in here as small handlers — each takes `(repo, pr, payload)` and
returns a markdown block.

Amend does not gate on dry mode: `gh pr edit` is silent (no watcher
notifications), so a body splice is reversible operator-side without
ever pinging the maintainer.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from dataclasses import asdict
from pathlib import Path

from temporalio import activity
from temporalio.exceptions import ApplicationError

from sweep.types import Message, forward_ledger


AMEND_INBOX = Path.home() / ".sweep" / "inbox" / "amend.jsonl"


def _append(inbox: Path, msg: Message) -> None:
    inbox.parent.mkdir(parents=True, exist_ok=True)
    with open(inbox, "a") as f:
        f.write(json.dumps(asdict(msg)) + "\n")


def _markers(kind: str) -> tuple[str, str]:
    open_m = f"<!-- sweep:amend:{kind} -->"
    close_m = f"<!-- /sweep:amend:{kind} -->"
    return open_m, close_m


def _splice(body: str, kind: str, block: str) -> str:
    """Splice ``block`` into ``body`` between the kind's markers.
    Replaces an existing block if the marker pair is present; appends
    otherwise. The block does not include the markers — this function
    owns the wrapping so the splice is symmetric with detection.
    """
    open_m, close_m = _markers(kind)
    wrapped = f"{open_m}\n{block}\n{close_m}"
    if open_m in body and close_m in body:
        pre, rest = body.split(open_m, 1)
        _, post = rest.split(close_m, 1)
        return f"{pre}{wrapped}{post}"
    sep = "" if body.endswith("\n") or not body else "\n\n"
    return f"{body}{sep}{wrapped}\n"


def _render_attestation_block(payload: dict) -> str | None:
    snippet = (payload or {}).get("attestation_links_md")
    if not snippet:
        return None
    return snippet


_HANDLERS = {
    "attestation": _render_attestation_block,
}


def _pr_body(repo: str, pr: int) -> str | None:
    """Read the current PR body. Returns None if the PR doesn't exist
    (gh exit != 0). Distinguishing "no PR" from "gh broken" is the
    caller's job — we treat any failure as no-PR for the noop semantic.
    """
    r = subprocess.run(
        ["gh", "pr", "view", str(pr), "--repo", repo, "--json", "body", "-q", ".body"],
        capture_output=True, text=True, timeout=20,
    )
    if r.returncode != 0:
        return None
    return r.stdout


def _pr_edit_body(repo: str, pr: int, body: str) -> tuple[int, str]:
    r = subprocess.run(
        ["gh", "pr", "edit", str(pr), "--repo", repo, "--body-file", "-"],
        input=body, capture_output=True, text=True, timeout=30,
    )
    return r.returncode, (r.stderr or "")[:300]


@activity.defn
async def kick_amend_card(repo: str, pr: int, kind: str,
                          sender: str = "attest",
                          incoming: Message | None = None,
                          payload: dict | None = None) -> str | None:
    """Deposit an amend card on amend.jsonl and signal amend-actor."""
    from sweep import observe
    from sweep.activities.pr_state import _signal_actor

    if not repo or not pr:
        return None
    ts = dt.datetime.now(dt.timezone.utc)
    slug = repo.replace("/", "-")
    msg_id = f"amend-{ts.strftime('%Y%m%dT%H%M%S')}-{slug}-{pr}-{kind}"
    msg = Message(
        msg_id=msg_id, sender=sender, intent=f"amend-{kind}",
        repo=repo, pr=pr, branch=None,
        payload={"kind": kind, **(payload or {})},
        ts=ts.isoformat(),
        ledger=forward_ledger(incoming),
    )
    try:
        _append(AMEND_INBOX, msg)
    except Exception as e:
        observe.event("amend_card_write_failed", repo=repo, pr=pr,
                      error_type=type(e).__name__, error=str(e)[:200])
        return None
    observe.event("amend_card_deposited", repo=repo, pr=pr,
                  block_kind=kind, sender=sender, msg_id=msg_id)
    return await _signal_actor("amend", msg)


@activity.defn
async def amend_cycle(msg: Message) -> dict:
    """Render the kind's block, splice it into the PR body, push the
    edit. Noop and return cleanly if the PR is gone or the body is
    already up to date.
    """
    from sweep import observe

    if not msg.repo or not msg.pr:
        raise ApplicationError(
            "amend: msg.repo and msg.pr required", non_retryable=True,
        )

    from sweep import pokayoke
    skip = pokayoke.amend_intake(msg)
    if skip:
        observe.event("amend_skipped", repo=msg.repo, pr=msg.pr,
                      reason=skip.code, detail=skip.detail,
                      msg_id=msg.msg_id)
        return {"status": "skipped", "reason": skip.code}

    payload = msg.payload or {}
    kind = payload.get("kind")
    handler = _HANDLERS.get(kind or "")
    if not handler:
        raise ApplicationError(
            f"amend: unknown kind {kind!r} (known: {sorted(_HANDLERS)})",
            non_retryable=True,
        )
    block = handler(payload)
    if not block:
        observe.event("amend_noop_no_block", repo=msg.repo, pr=msg.pr,
                      block_kind=kind, msg_id=msg.msg_id)
        return {"status": "noop", "reason": "handler returned no block"}

    body = _pr_body(msg.repo, int(msg.pr))
    if body is None:
        observe.event("amend_noop_no_pr", repo=msg.repo, pr=msg.pr,
                      block_kind=kind, msg_id=msg.msg_id)
        return {"status": "noop", "reason": "pr not found"}

    new_body = _splice(body, kind, block)
    if new_body == body:
        observe.event("amend_noop_unchanged", repo=msg.repo, pr=msg.pr,
                      block_kind=kind, msg_id=msg.msg_id)
        return {"status": "noop", "reason": "body already current"}

    rc, err = _pr_edit_body(msg.repo, int(msg.pr), new_body)
    if rc != 0:
        raise ApplicationError(
            f"gh pr edit failed (rc={rc}): {err}", non_retryable=True,
        )
    observe.event("amend_applied", repo=msg.repo, pr=msg.pr,
                  block_kind=kind, msg_id=msg.msg_id,
                  delta_bytes=len(new_body) - len(body))
    return {"status": "applied", "kind": kind,
            "delta_bytes": len(new_body) - len(body)}
