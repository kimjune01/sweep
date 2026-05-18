"""Check — upstream CI watcher.

Fetches `/repos/{repo}/commits/{sha}/check-runs` for a PR head, classifies
each check's conclusion, and emits one remit card per failed check so
the post-submit engagement loop picks it up like a maintainer comment.

Why "check": mirrors GitHub's own vocabulary (`check_run`, `check_suite`,
`gh pr checks`) — one-to-one from API to actor. Distinct from `attest`
(our local belief the fix works); `check` is the external ratification
upstream CI provides. For denylisted repos (cubecl, zulip, anything we
can't run locally) `check` IS the only attestation path.

Producers:
  - `respond` / `submit` after `git push` (our own pushes — strongest
    signal, zero API cost to detect)
  - background SHA-poller (catch-all for pushes we didn't initiate;
    not yet wired)

Debounce on (repo, pr): multiple kicks within a tight window should
collapse to one fetch. Today's scaffold relies on SkillActor.deliver's
msg_id dedup (same SHA → same msg_id → single fire). Per-PR timer
debounce for SHA-stable rapid kicks is future work.

Monoidal contract: `check_cycle` is read-mostly. Given the same
(repo, pr, sha) it:
  - Fetches the same `/check-runs` response (gh_io cache TTL pins
    intra-window calls; cerify runs back-to-back in the same second).
  - Routes each failed check to remit using a deterministic msg_id
    keyed on (repo, pr, sha, check_name, conclusion). SkillActor.deliver
    is idempotent on msg_id, so re-runs are no-ops on the consumer.
  - Returns a stable summary `{sha, total, passed, failed, pending,
    failed_names}` with no wall-clock fields, so cerify's default
    strict equiv accepts back-to-back runs.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict
from pathlib import Path

from temporalio import activity
from temporalio.exceptions import ApplicationError

from sweep.types import Message, forward_ledger


CHECK_INBOX = Path.home() / ".sweep" / "inbox" / "check.jsonl"


# GitHub `conclusion` values fall into three actionable buckets. Pending
# (status != "completed", conclusion null) is a fourth bucket handled
# separately. "neutral" and "skipped" are pass-equivalent — the check
# ran and produced no objection. "stale" and "action_required" are
# fail-equivalent: something's wrong and the operator should see it.
_PASS_CONCLUSIONS = {"success", "neutral", "skipped"}
_FAIL_CONCLUSIONS = {"failure", "timed_out", "cancelled",
                     "action_required", "stale"}


def _append(inbox: Path, msg: Message) -> None:
    inbox.parent.mkdir(parents=True, exist_ok=True)
    with open(inbox, "a") as f:
        f.write(json.dumps(asdict(msg)) + "\n")


def _slug(s: str) -> str:
    """File-safe ascii slug for msg_id components. Conservative — only
    keeps alnum + dash + underscore; everything else becomes dash."""
    out = []
    for c in s:
        if c.isalnum() or c in ("-", "_"):
            out.append(c)
        else:
            out.append("-")
    return "".join(out).strip("-")[:60] or "x"


def _gh_api_json(path: str, timeout: int = 15) -> object | None:
    """Best-effort `gh api` GET; returns parsed JSON or None on any
    failure. Used by `kick_check_from_subject` to resolve a CheckSuite
    notification subject into (repo, head_sha, pr). Defensive — every
    failure is silent because the caller is on the notification
    hot-path and a bad subject must not stall poll progress."""
    import subprocess
    try:
        proc = subprocess.run(
            ["gh", "api", path], capture_output=True, text=True,
            timeout=timeout, check=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    try:
        return json.loads(proc.stdout or "null")
    except json.JSONDecodeError:
        return None


def _resolve_checksuite_subject(subject_url: str) -> tuple[str, str, int] | None:
    """Resolve a CheckSuite/WorkflowRun notification subject URL into
    (repo, head_sha, pr_number). Returns None if any step fails or no
    PR is associated with the head sha (CI fired on main, or a branch
    with no open PR — nothing to ratify).

    Two gh calls: one for the suite resource (head_sha lives on it),
    one for `/commits/{sha}/pulls` (head_sha → PR). Per-tick volume is
    bounded by unread CheckSuite count; not currently cached.
    """
    rel = subject_url
    for prefix in ("https://api.github.com", "http://api.github.com"):
        if rel.startswith(prefix):
            rel = rel[len(prefix):]
            break
    suite = _gh_api_json(rel)
    if not isinstance(suite, dict):
        return None
    head_sha = str(suite.get("head_sha") or "")
    if not head_sha:
        return None
    repo_obj = suite.get("repository") or {}
    repo = (str(repo_obj.get("full_name")) if isinstance(repo_obj, dict)
            else "")
    if not repo:
        return None
    pulls = _gh_api_json(f"/repos/{repo}/commits/{head_sha}/pulls")
    if not isinstance(pulls, list) or not pulls:
        return None
    first = pulls[0]
    if not isinstance(first, dict):
        return None
    try:
        pr_num = int(first.get("number") or 0)
    except (TypeError, ValueError):
        return None
    if pr_num <= 0:
        return None
    return repo, head_sha, pr_num


@activity.defn
async def kick_check_from_subject(subject_url: str,
                                  sender: str = "notification-poller",
                                  incoming: Message | None = None
                                  ) -> str | None:
    """Resolve a CheckSuite/WorkflowRun notification subject and deposit
    the standard check card. Used by NotificationPoller so it stays a
    dumb emitter — all resolution + enrichment knowledge lives here.

    Returns the signal-result of the inner `kick_check_card`, or None
    if the subject couldn't be resolved (no PR for the head sha, or
    gh API failure). Resolution failures emit
    `check_subject_unresolved` so the operator can spot patterns; the
    notification itself stays unread so a later tick can retry once
    GitHub's indexing catches up.
    """
    from sweep import observe
    if not subject_url:
        return None
    import asyncio
    resolved = await asyncio.to_thread(_resolve_checksuite_subject,
                                       subject_url)
    if not resolved:
        observe.event("check_subject_unresolved",
                      subject_url=subject_url[:200], sender=sender)
        return None
    repo, head_sha, pr = resolved
    return await kick_check_card(
        repo=repo, pr=pr, head_sha=head_sha,
        sender=sender, incoming=incoming,
    )


@activity.defn
async def kick_check_card(repo: str, pr: int, head_sha: str,
                          sender: str = "submit",
                          incoming: Message | None = None) -> str | None:
    """Deposit one check card on check.jsonl and signal check-actor.

    `head_sha` is the commit the actor will fetch checks for. msg_id is
    keyed on (repo, pr, sha[:12]) so two kicks for the same push (e.g.
    submit + the SHA-poller's catch-all) collapse via SkillActor's
    deliver-time dedup. A new push produces a new sha → a new msg_id →
    a fresh fetch.
    """
    from sweep import observe
    from sweep.activities.pr_state import _signal_actor

    if not repo or not pr or not head_sha:
        return None
    ts = dt.datetime.now(dt.timezone.utc)
    slug = repo.replace("/", "-")
    msg_id = f"check-{slug}-{pr}-{head_sha[:12]}"
    msg = Message(
        msg_id=msg_id,
        sender=sender,
        intent="check",
        repo=repo,
        pr=pr,
        branch=None,
        payload={"head_sha": head_sha},
        ts=ts.isoformat(),
        ledger=forward_ledger(incoming),
    )
    try:
        _append(CHECK_INBOX, msg)
    except Exception as e:
        observe.event("check_card_write_failed", repo=repo, pr=pr,
                      error_type=type(e).__name__, error=str(e)[:200])
        return None
    observe.event("check_card_deposited", repo=repo, pr=pr,
                  sha=head_sha[:12], sender=sender, msg_id=msg_id)
    return await _signal_actor("check", msg)


async def _route_fail_to_remit(incoming: Message, sha: str,
                               check_name: str, conclusion: str) -> None:
    """Drop one remit card for a failed check. Deterministic msg_id keyed
    on (repo, pr, sha, check_name, conclusion) so retries / cerify
    back-to-back runs are no-ops on the consumer side via
    SkillActor.deliver dedup.

    Bypasses `kick_remit_card` because that helper builds a timestamp-
    based msg_id and we need determinism for the monoidal contract.
    """
    from sweep import observe
    from sweep.activities.pr_state import _signal_actor
    from sweep.activities.remit import REMIT_INBOX

    if not incoming.repo or not incoming.pr:
        return
    slug = incoming.repo.replace("/", "-")
    name_slug = _slug(check_name)
    msg_id = (f"remit-check-{slug}-{incoming.pr}-{sha[:12]}-"
              f"{name_slug}-{conclusion}")
    msg = Message(
        msg_id=msg_id,
        sender="check",
        intent="classify",
        repo=incoming.repo,
        pr=incoming.pr,
        branch=None,
        payload={
            "trigger": "ci_check_failed",
            "check_name": check_name,
            "conclusion": conclusion,
            "head_sha": sha,
        },
        ts=dt.datetime.now(dt.timezone.utc).isoformat(),
        ledger=forward_ledger(incoming),
    )
    try:
        _append(REMIT_INBOX, msg)
    except Exception as e:
        observe.event("check_route_failed", repo=incoming.repo,
                      pr=incoming.pr, check_name=check_name,
                      error_type=type(e).__name__, error=str(e)[:200])
        return
    observe.event("check_routed_to_remit", repo=incoming.repo,
                  pr=incoming.pr, sha=sha[:12], check_name=check_name,
                  conclusion=conclusion, msg_id=msg_id)
    await _signal_actor("remit", msg)


@activity.defn
async def check_cycle(msg: Message) -> dict:
    """Fetch CI checks for the PR's head sha; route failures to remit.

    Returns `{sha, total, passed, failed, pending, failed_names}` —
    summary only, no wall-clock fields, so cerify's strict equiv accepts
    the second back-to-back run. Per-check side effects (remit writes
    and signals) are individually idempotent on msg_id.
    """
    from sweep import gh_io, observe

    if not msg.repo or not msg.pr:
        raise ApplicationError("check: msg.repo and msg.pr required",
                               non_retryable=True)
    sha = (msg.payload or {}).get("head_sha")
    if not sha:
        raise ApplicationError("check: payload.head_sha required",
                               non_retryable=True)

    try:
        data = gh_io.api(
            f"/repos/{msg.repo}/commits/{sha}/check-runs", ttl=60,
        )
    except Exception as e:
        observe.event("check_fetch_failed", repo=msg.repo, pr=msg.pr,
                      sha=sha[:12], error_type=type(e).__name__,
                      error=str(e)[:200])
        raise ApplicationError(
            f"check: gh_io failed for {msg.repo}@{sha[:12]}: {e}",
            non_retryable=False,  # transient — let Temporal retry
        ) from e

    runs = data.get("check_runs", []) if isinstance(data, dict) else []
    passed = failed = pending = 0
    failed_names: list[str] = []

    for run in runs:
        if not isinstance(run, dict):
            continue
        name = str(run.get("name") or "")
        status = run.get("status")
        conclusion = run.get("conclusion")
        if status != "completed":
            pending += 1
            continue
        if conclusion in _PASS_CONCLUSIONS:
            passed += 1
        elif conclusion in _FAIL_CONCLUSIONS:
            failed += 1
            failed_names.append(name)
            await _route_fail_to_remit(msg, sha, name, str(conclusion))
        else:
            # Unknown conclusion — count as pending so we re-check later
            # rather than silently dropping. New GitHub conclusion values
            # land here until the constant sets are updated.
            pending += 1

    observe.event("check_cycle_complete", repo=msg.repo, pr=msg.pr,
                  sha=sha[:12], total=len(runs), passed=passed,
                  failed=failed, pending=pending, msg_id=msg.msg_id)

    # All-green: kick ping. The ping actor re-verifies all three
    # preconditions (attest manifest, gh check-runs, no prior draft)
    # deterministically before drafting — so over-kicking here is
    # cheap and idempotent.
    if msg.pr and total > 0 and passed > 0 and failed == 0 and pending == 0:
        try:
            from sweep.activities.ping import kick_ping_card
            await kick_ping_card(
                repo=msg.repo, pr=int(msg.pr), head_sha=sha,
                source="check_cycle", incoming=msg,
            )
        except Exception as e:
            observe.event("ping_kick_from_check_failed",
                          repo=msg.repo, pr=msg.pr, sha=sha[:12],
                          error_type=type(e).__name__, error=str(e)[:200])

    return {
        "sha": sha,
        "total": len(runs),
        "passed": passed,
        "failed": failed,
        "pending": pending,
        "failed_names": sorted(failed_names),
    }
