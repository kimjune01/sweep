"""Compose — PR body writer / amender between attest and submit.

Sits in the production lane after attest passes (its hard precondition
is `attestation_hash` on the card; missing it halts the actor). Two
shapes:

  new PR     — render a compose-owned body section, hand to submit which
               creates the PR via /drip --push using the rendered body.
  existing PR (backfill) — splice the compose-owned section into the
               live PR body via marker-pair (idempotent edit, same shape
               as amend). gh pr edit is silent, no maintainer notification.

Marker pair: `<!-- sweep:compose -->...<!-- /sweep:compose -->`. Re-runs
replace the prior block in place — convergent under repeated application.

The render is delegated to a single function (`_render_compose_block`)
which is a template today and becomes a /compose skill call later.
Returning None is the "nothing to write" case (skill rejected or template
declined) and routes to the rejected-as-third-outcome branch rather than
silently acking.

Outcomes (per Trick #7 / #8 of the skill-actor patterns):
  applied         — body changed and gh edit succeeded
  noop_no_pr      — pr not on GH; falls through to submit for creation
  noop_unchanged  — splice was a no-op; body already current
  noop_no_block   — renderer returned nothing
  rejected_no_attestation — upstream wiring bug; halts the actor

Compliance counters (#9): `clean_fast` (renderer returned content) vs
`fallback` (default template used). Surfaced via observe.incr so future
skill drift is visible without grepping events.
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

COMPOSE_INBOX = Path.home() / ".sweep" / "inbox" / "compose.jsonl"

# Marker pair — same shape as amend's per-kind markers, but compose
# owns a single section (no `kind` axis). One section per PR; re-runs
# replace it. HTML-comment so it doesn't render in the maintainer's
# view of the body.
_COMPOSE_MARKER_OPEN = "<!-- sweep:compose -->"
_COMPOSE_MARKER_CLOSE = "<!-- /sweep:compose -->"


def _splice_compose(body: str, block: str) -> str:
    """Replace the compose section in `body` with `block` (markers
    added). If the markers are absent, append the section. Symmetric
    with detection — passing the same (body, block) twice converges."""
    wrapped = f"{_COMPOSE_MARKER_OPEN}\n{block}\n{_COMPOSE_MARKER_CLOSE}"
    if _COMPOSE_MARKER_OPEN in body and _COMPOSE_MARKER_CLOSE in body:
        pre, rest = body.split(_COMPOSE_MARKER_OPEN, 1)
        _, post = rest.split(_COMPOSE_MARKER_CLOSE, 1)
        return f"{pre}{wrapped}{post}"
    sep = "" if body.endswith("\n") or not body else "\n\n"
    return f"{body}{sep}{wrapped}\n"


def _render_compose_block(msg: Message, attestation_hash: str) -> tuple[str | None, str]:
    """Render the compose-owned body section.

    Returns (block, provenance):
      block: the section content (no markers), or None if there's
             nothing to write — caller routes to noop_no_block.
      provenance: 'skill' | 'template' | 'fallback' — feeds compose
             compliance counters.

    Today: pure template — references the attestation footer that amend
    publishes. When the /compose skill lands, this function calls it and
    falls back to the template on skill failure / empty output.
    """
    short_hash = attestation_hash[:12] if attestation_hash else ""
    if not short_hash:
        return None, "fallback"
    lines = [
        f"_Sweep attestation `{short_hash}` — see the receipts footer below._",
    ]
    return "\n".join(lines), "template"


def _pr_body(repo: str, pr: int) -> str | None:
    """Read the PR body. Returns None if gh fails (PR missing, network
    flake, perms) — caller treats as 'no PR yet'."""
    r = subprocess.run(
        ["gh", "pr", "view", str(pr), "--repo", repo,
         "--json", "body", "-q", ".body"],
        capture_output=True, text=True, timeout=20,
    )
    if r.returncode != 0:
        return None
    return r.stdout


def _pr_edit_body(repo: str, pr: int, body: str) -> tuple[int, str]:
    r = subprocess.run(
        ["gh", "pr", "edit", str(pr), "--repo", repo,
         "--body-file", "-"],
        input=body, capture_output=True, text=True, timeout=30,
    )
    return r.returncode, (r.stderr or "")[:300]


@activity.defn
async def kick_compose_card(repo: str, branch: str, pr: int | None = None,
                            sender: str = "qa",
                            attestation_hash: str | None = None,
                            incoming: Message | None = None) -> str | None:
    """Deposit a verified-fix card on compose.jsonl and signal
    compose-actor. Called by qa when verdict=pass and a fix is ready
    to be packaged for the maintainer.

    Compose then writes the PR text and hands off to submit for the
    final-bastion gate."""
    from sweep import observe
    from sweep.activities.pr_state import _signal_actor

    ts = dt.datetime.now(dt.timezone.utc)
    slug = repo.replace("/", "-")
    pr_part = pr if pr is not None else "new"
    msg_id = f"compose-{ts.strftime('%Y%m%dT%H%M%S')}-{slug}-{pr_part}"
    payload = {}
    if attestation_hash:
        payload["attestation_hash"] = attestation_hash
    msg = Message(
        msg_id=msg_id,
        sender=sender,
        intent="compose",
        repo=repo,
        pr=pr,
        branch=branch,
        payload=payload,
        ts=ts.isoformat(),
        ledger=forward_ledger(incoming),
    )
    COMPOSE_INBOX.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(COMPOSE_INBOX, "a") as f:
            f.write(json.dumps(asdict(msg)) + "\n")
    except Exception as e:
        observe.event("compose_card_write_failed", repo=repo, branch=branch,
                      error_type=type(e).__name__, error=str(e)[:200])
        return None
    observe.event("compose_card_deposited", repo=repo, branch=branch,
                  pr=pr, sender=sender, msg_id=msg_id)
    return await _signal_actor("compose", msg)


@activity.defn
async def compose_cycle(msg: Message) -> dict:
    """Two shapes:
      - msg.pr set + PR exists → splice compose section into body via
        marker pair, gh pr edit, exit. Idempotent — re-runs converge.
      - msg.pr unset OR PR missing → render block, hand to submit which
        creates the PR carrying the rendered body in its payload.

    Attestation is a hard precondition either way — without it, upstream
    wiring is broken and we halt the actor rather than push unverified
    code or write a body referencing a hash we don't have.
    """
    if not msg.repo or not msg.branch:
        raise ApplicationError("compose: repo + branch required",
                               non_retryable=True)
    from sweep import observe
    from sweep.activities.submit import kick_submit_card

    attestation_hash = (msg.payload or {}).get("attestation_hash")
    if not attestation_hash:
        observe.incr("compose_outcome:rejected_no_attestation")
        raise ApplicationError(
            f"compose: missing attestation_hash on {msg.repo}@{msg.branch} "
            f"(msg_id={msg.msg_id}, sender={msg.sender}) — upstream did not "
            f"route through attest",
            non_retryable=True,
        )

    block, provenance = _render_compose_block(msg, attestation_hash)
    observe.incr(f"compose_render:{provenance}")
    if block is None:
        observe.event("compose_noop_no_block", repo=msg.repo,
                      branch=msg.branch, pr=msg.pr, msg_id=msg.msg_id,
                      provenance=provenance)
        observe.incr("compose_outcome:noop_no_block")
        return {"status": "noop_no_block", "provenance": provenance}

    # Existing-PR path: splice into the live body, idempotent.
    if msg.pr:
        body = _pr_body(msg.repo, int(msg.pr))
        if body is not None:
            new_body = _splice_compose(body, block)
            if new_body == body:
                observe.event("compose_noop_unchanged", repo=msg.repo,
                              branch=msg.branch, pr=msg.pr, msg_id=msg.msg_id)
                observe.incr("compose_outcome:noop_unchanged")
                return {"status": "noop_unchanged"}
            rc, err = _pr_edit_body(msg.repo, int(msg.pr), new_body)
            if rc != 0:
                # Treat as transient; let SkillActor's retry policy take
                # another swing before halting. Non_retryable=False on
                # the raise so the SkillActor's RetryPolicy honors it.
                raise ApplicationError(
                    f"compose: gh pr edit failed (rc={rc}): {err}",
                    non_retryable=False,
                )
            observe.event("compose_applied", repo=msg.repo, branch=msg.branch,
                          pr=msg.pr, msg_id=msg.msg_id,
                          delta_bytes=len(new_body) - len(body),
                          provenance=provenance)
            observe.incr("compose_outcome:applied")
            return {"status": "applied",
                    "delta_bytes": len(new_body) - len(body),
                    "provenance": provenance}
        # PR not on GH (deleted/missing) — fall through to submit, same
        # as the no-pr case. Distinct event so leakdog can see the slip.
        observe.event("compose_noop_no_pr", repo=msg.repo, branch=msg.branch,
                      pr=msg.pr, msg_id=msg.msg_id)
        observe.incr("compose_outcome:noop_no_pr")

    # No PR yet: hand to submit. Submit/drip currently writes its own
    # body inline; passing the rendered block through `pr_body` lets the
    # future submit shape consume it without compose having to re-render.
    wf_id = await kick_submit_card(
        msg.repo, msg.branch, msg.pr,
        sender="compose",
        attestation_hash=attestation_hash,
        incoming=msg,
    )
    observe.event("compose_handoff_submit", repo=msg.repo, branch=msg.branch,
                  pr=msg.pr, msg_id=msg.msg_id,
                  submit_wf=wf_id or "(no-signal)",
                  provenance=provenance)
    observe.incr("compose_outcome:handoff_submit")
    return {"status": "handoff_submit", "kicked_submit": wf_id,
            "provenance": provenance}
