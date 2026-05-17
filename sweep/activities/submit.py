"""Submit — the new-PR-create gate.

Sits between qa's verified fix (eventually via compose-actor) and
respond's push. Single job: gate the new-public-commitment moment.

Three things submit does that no upstream actor does:

  1. Honors dry mode. Dry is narrowly scoped — it means "no new public
     commitments" — and submit is the only actor that gates on it. The
     gating happens at the inbox-pull point (pause_gate.should_idle) so
     cards pile in submit.jsonl while dry is on; `sweep dry off` drains.

  2. Final-bastion re-verify. Attestation hash + repo eviction + AI
     policy + still-mergeable. Cheap re-checks against live state right
     before the push, in case the world moved while the card waited.
     (Full battery lands in a follow-up; this skeleton trusts upstream.)

  3. Delegates the actual push. Once gates pass, submit hands off to
     respond-actor with intent="publish" — respond owns the /drip
     subprocess and the budget attribution for the gh calls.

The split lets submit stay small and auditable (a list of gates) while
respond stays mechanical (push verbs). Different concerns, different
actors.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict
from pathlib import Path

from temporalio import activity
from temporalio.exceptions import ApplicationError

from sweep.types import Message

SUBMIT_INBOX = Path.home() / ".sweep" / "inbox" / "submit.jsonl"


@activity.defn
async def kick_submit_card(repo: str, branch: str, pr: int | None = None,
                           sender: str = "qa",
                           attestation_hash: str | None = None) -> str | None:
    """Deposit a ready-to-publish card on submit.jsonl and signal
    submit-actor. Called by qa (eventually compose) when a fix is
    verified and ready to land as a new PR or push.

    Card carries the publish-time inputs: repo, branch, optional pr
    number (rebase to existing PR vs. new), and attestation hash for
    submit's re-verify step."""
    from sweep import observe
    from sweep.activities.pr_state import _signal_actor

    ts = dt.datetime.now(dt.timezone.utc)
    slug = repo.replace("/", "-")
    pr_part = pr if pr is not None else "new"
    msg_id = f"submit-{ts.strftime('%Y%m%dT%H%M%S')}-{slug}-{pr_part}"
    payload = {}
    if attestation_hash:
        payload["attestation_hash"] = attestation_hash
    msg = Message(
        msg_id=msg_id,
        sender=sender,
        intent="publish",
        repo=repo,
        pr=pr,
        branch=branch,
        payload=payload,
        ts=ts.isoformat(),
    )
    SUBMIT_INBOX.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(SUBMIT_INBOX, "a") as f:
            f.write(json.dumps(asdict(msg)) + "\n")
    except Exception as e:
        observe.event("submit_card_write_failed", repo=repo, branch=branch,
                      error_type=type(e).__name__, error=str(e)[:200])
        return None
    observe.event("submit_card_deposited", repo=repo, branch=branch,
                  pr=pr, sender=sender, msg_id=msg_id)
    return await _signal_actor("submit", msg)


async def _attestation_gate(repo: str, branch: str | None) -> tuple[bool, str]:
    """Find the worktree's attestations dir and run the deterministic
    verifier. Returns (ok, reason). Refuses push if no attestation
    manifest exists, if the verifier rejects it, or if the worktree
    can't be located.

    Convention: each PR ships an `attestations/<slug>/` dir with
    `manifest.json` + `after.txt` (test stdout on fix branch). Optional
    `before.txt` shows the test on master. Both the hygraph (in
    repo-hypotheses/) and the attestation live with the change — no
    'trust me, I checked' moves."""
    if not branch:
        return False, "no branch — can't locate worktree"
    from sweep.activities.worktree import ensure_worktree
    from sweep.attestation_verify import gate_push
    try:
        worktree = await ensure_worktree(repo, branch)
    except Exception as e:
        return False, f"ensure_worktree: {type(e).__name__}: {e}"
    att_root = Path(worktree) / "attestations"
    if not att_root.exists():
        return False, f"no attestations/ dir in worktree {worktree}"
    candidates = [p for p in att_root.iterdir()
                  if p.is_dir() and (p / "manifest.json").exists()]
    if not candidates:
        return False, f"no attestations/*/manifest.json in {att_root}"
    if len(candidates) > 1:
        names = ", ".join(p.name for p in candidates)
        return False, f"ambiguous attestation dirs: {names}"
    return gate_push(candidates[0])


async def _final_checks(repo: str, pr: int | None) -> tuple[bool, str]:
    """Cheap re-checks against live state right before push. Returns
    (ok, reason). Order matters: cheapest checks first, so a fast no
    short-circuits the expensive ones.

    Checks:
      1. Repo on kill list (operator hard-banned this repo).
      2. Repo on evicted list (sift evicted it while card waited).
      3. Repo AI policy went hostile (24h-cached gh lookup).
      4. If pr exists: still mergeable per live gh state.

    Not checked here: attestation hash. That belongs upstream — the
    push artifact (attestation) is hashed at create time and the
    drip/respond layer re-hashes at push time via the existing
    gate-pr-create hook (see attestations.py / fuses.py). Adding a
    third re-hash here would duplicate the gate without adding signal.
    """
    from sweep.activities.sift import _on_kill_list, _on_evicted_list
    if _on_kill_list(repo):
        return False, "repo on kill list"
    if _on_evicted_list(repo):
        return False, "repo on evicted list"
    try:
        from sweep import gh_io
        if gh_io.repo_ai_policy(repo) == "hostile":
            return False, "repo AI policy went hostile"
    except Exception as e:
        from sweep import observe
        observe.event("submit_policy_check_error", repo=repo,
                      error_type=type(e).__name__, error=str(e)[:200])
    if pr is not None:
        try:
            from sweep.activities.pr_state import gh_pr_view
            state = await gh_pr_view(repo, int(pr))
            mergeable = (state.signals or {}).get("mergeable", "")
            if mergeable == "CONFLICTING":
                return False, "PR became conflicting since prep"
        except Exception as e:
            from sweep import observe
            observe.event("submit_mergeable_check_error",
                          repo=repo, pr=pr,
                          error_type=type(e).__name__, error=str(e)[:200])
    return True, "ok"


@activity.defn
async def submit_cycle(msg: Message) -> dict:
    """Gate one publish card and delegate the push to respond.

    Dry-mode hold lives upstream at pause_gate (the actor doesn't even
    pull the card while dry is on), so by the time this activity runs
    we know dry is off. The final-check battery is the gate; respond is
    the doer.

    On gate failure: ack the card (returns rather than raises) and emit
    submit_gate_failed. The card is consumed — re-evaluating it would
    likely fail the same way, and the upstream signal that produced it
    (qa-converged) will fire again on the next pass if conditions
    change. Operator can re-kick manually if intended.
    """
    if not msg.repo or not msg.branch:
        raise ApplicationError("submit: repo + branch required",
                               non_retryable=True)
    from sweep import observe
    from sweep.activities.skill_runner import respond_cycle

    ok, reason = await _final_checks(msg.repo, msg.pr)
    if not ok:
        observe.event("submit_gate_failed", repo=msg.repo, branch=msg.branch,
                      pr=msg.pr, reason=reason, msg_id=msg.msg_id)
        return {"published": False, "gated": True, "reason": reason}

    # Attestation gate: the deterministic verifier re-parses the
    # committed test-attestation.txt and refuses to push if 0 tests
    # ran, the expected test isn't present, or any test failed.
    # No valid attestation → no push. Production-side vibes can't
    # bypass this.
    ok, reason = await _attestation_gate(msg.repo, msg.branch)
    if not ok:
        observe.event("submit_attestation_failed", repo=msg.repo, branch=msg.branch,
                      pr=msg.pr, reason=reason, msg_id=msg.msg_id)
        return {"published": False, "gated": True, "reason": f"attestation: {reason}"}

    # Synthesize a respond-shaped message and delegate. respond_cycle
    # records its own subprocess budget and runs /drip --push.
    publish_msg = Message(
        msg_id=f"{msg.msg_id}-publish",
        sender="submit",
        intent="publish",
        repo=msg.repo,
        pr=msg.pr,
        branch=msg.branch,
        payload=msg.payload,
        ts=dt.datetime.now(dt.timezone.utc).isoformat(),
    )
    result = await respond_cycle(publish_msg)
    observe.event("submit_published", repo=msg.repo, branch=msg.branch,
                  pr=msg.pr, rc=result.get("rc", 0),
                  msg_id=msg.msg_id)
    return {"published": True, "respond_result": result}
