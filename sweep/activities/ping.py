"""Ping — both-greens correlator for the polite maintainer nudge.

Sits past compose/amend in the engagement lane. Two input streams:

  attest_routed verdict=pass head_sha=X     (substrate-side green)
  check_cycle_complete failed=0 pending=0   (maintainer-side CI green)

When both have fired for the same head SHA on the same (repo, pr), the
ping actor drafts a polite nudge comment and deposits it on the human
inbox for operator approval. The operator approves via `sweep ping
approve <id>` or dismisses via `sweep ping dismiss <id>`.

The both-greens condition is the social license. Pinging on either
signal alone would be bot-noise; pinging on the intersection is earned
— "your CI and a locally-run attest cycle both agree this fix passes."

Idempotent on head SHA: once drafted for SHA X, never re-draft for X.
A new push (new SHA) re-enables. The dedup key for the actor's
_seen_msg_ids is exactly (repo, pr, sha).
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict
from pathlib import Path

from temporalio import activity
from temporalio.exceptions import ApplicationError

from sweep.types import Message, forward_ledger

PING_INBOX = Path.home() / ".sweep" / "inbox" / "ping.jsonl"
HUMAN_INBOX = Path.home() / ".sweep" / "inbox" / "human.jsonl"
# Deterministic per-SHA ping ledger. Append-only; one row per
# (repo, pr, sha) we've drafted a ping for. The file is the truth
# for "already pinged this SHA?" — events.jsonl is observability,
# not authority.
PING_LEDGER = Path.home() / ".sweep" / "control" / "ping_drafted.jsonl"
# Same operator kill switch tissue/post honor. When set, ping_cycle
# refuses to even draft — drafts piling up while post is disabled
# would all fire at once on re-enable, defeating the safety the
# flag exists for. Cleared by `rm ~/.sweep/control/post_disabled`.
POST_DISABLED_FLAG = Path.home() / ".sweep" / "control" / "post_disabled"


def _attest_manifest_path(repo: str, pr: int) -> Path:
    """Path to the attestation manifest for (repo, pr). Co-located
    with the substrate's own repo at attestations/<org>-<repo>/."""
    sweep_repo = Path(__file__).resolve().parent.parent.parent
    org_repo = repo.replace("/", "-")
    return sweep_repo / "attestations" / org_repo / f"issue-{pr}-manifest.json"


def _attest_pass_for_sha(repo: str, pr: int, head_sha: str) -> bool:
    """Ground truth: does an attestation manifest exist for (repo, pr)
    pinned to head_sha? Deterministic file check."""
    p = _attest_manifest_path(repo, pr)
    if not p.exists():
        return False
    try:
        manifest = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    pinned = manifest.get("head_sha") or ""
    return bool(pinned) and (pinned == head_sha or head_sha.startswith(pinned))


def _gh_check_runs_for_sha(repo: str, head_sha: str) -> tuple[int, int, int]:
    """Ground truth: query GitHub for check-runs at this SHA. Returns
    (total, passed, failed_or_pending). Deterministic gh call (with
    short TTL cache via gh_io). Caller checks
    failed_or_pending == 0 AND passed > 0 for the all-green condition.
    """
    from sweep import gh_io
    try:
        data = gh_io.api(
            f"repos/{repo}/commits/{head_sha}/check-runs",
            ttl=60,
        )
    except Exception:
        return (0, 0, 1)  # treat fetch error as not-yet-green
    runs = (data or {}).get("check_runs") or []
    if not isinstance(runs, list):
        return (0, 0, 1)
    _PASS = {"success", "neutral", "skipped"}
    _FAIL = {"failure", "timed_out", "cancelled", "action_required",
             "stale", "startup_failure"}
    passed = 0
    failed_or_pending = 0
    for r in runs:
        if not isinstance(r, dict):
            continue
        status = r.get("status")
        conclusion = (r.get("conclusion") or "").lower()
        if status != "completed":
            failed_or_pending += 1
        elif conclusion in _PASS:
            passed += 1
        elif conclusion in _FAIL:
            failed_or_pending += 1
        else:
            failed_or_pending += 1
    return (len(runs), passed, failed_or_pending)


def _already_drafted(repo: str, pr: int, head_sha: str) -> bool:
    """Ground truth: have we drafted a ping for (repo, pr, sha)?
    Reads PING_LEDGER — file-as-authority, not event-scan."""
    if not PING_LEDGER.exists():
        return False
    try:
        for line in PING_LEDGER.read_text().splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (row.get("repo") == repo
                    and row.get("pr") in (pr, str(pr))
                    and row.get("head_sha") == head_sha):
                return True
    except OSError:
        return False
    return False


def _record_drafted(repo: str, pr: int, head_sha: str, draft_id: str) -> None:
    """Append the per-SHA draft record to PING_LEDGER. Idempotent —
    `_already_drafted` is the read-side guard."""
    PING_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
        "repo": repo,
        "pr": pr,
        "head_sha": head_sha,
        "draft_id": draft_id,
    }
    try:
        with open(PING_LEDGER, "a") as f:
            f.write(json.dumps(row) + "\n")
    except OSError:
        pass  # best-effort; double-draft is acceptable failure mode


def _render_ping(repo: str, pr: int, head_sha: str,
                  ci_status: str = "all_green") -> str:
    """Two templates by `ci_status`:

      all_green  — maintainer already has independent CI ratification.
                   Nudge: ready for review when they have a moment.
      absent     — CI hasn't run (likely first-time-contributor gate).
                   Direct ask: enable the CI run so they can verify.

    No "friendly nudge" hedge in the absent case — the maintainer
    needs to do a specific thing (click Approve and run) and we should
    say so."""
    short = head_sha[:7] if head_sha else ""
    pin = f" (head `{short}`)" if short else ""
    if ci_status == "absent":
        # shape 3: reason we cannot + action taken in response + direct ask
        return f"CI did not run; attested locally instead{pin} (receipts in body). Please approve a run."
    # all_green — shape 1: direct ask
    return f"CI and local attest both green{pin}. Ready for review."


def _default_scheduled_for() -> str:
    """When TZ inference isn't wired yet, default schedule = now (the
    metronome's next ping-tick fires immediately on eligibility).
    Future: per-maintainer TZ → next 9-10am window in their local TZ."""
    return dt.datetime.now(dt.timezone.utc).isoformat()


@activity.defn
async def kick_ping_card(
    repo: str, pr: int, head_sha: str,
    source: str = "attest",
    incoming: Message | None = None,
    scheduled_for: str | None = None,
) -> str | None:
    """Deposit a ping card on ping.jsonl and signal ping-actor. Called
    from attest_cycle (on verdict=pass) and check_cycle_complete (on
    all-green). The card's msg_id encodes (repo, pr, sha) so duplicate
    kicks dedup at the SkillActor's _seen_msg_ids.

    `scheduled_for` is the earliest ISO timestamp at which the metronome
    is allowed to actually fire the ping. Default = now (immediate).
    TZ-aware schedulers can pass a future time so the draft sits
    parked until the right hour."""
    from sweep import observe
    from sweep.activities.pr_state import _signal_actor

    if not repo or not pr or not head_sha:
        return None
    ts = dt.datetime.now(dt.timezone.utc)
    slug = repo.replace("/", "-")
    msg_id = f"ping-{slug}-{pr}-{head_sha[:12]}"
    msg = Message(
        msg_id=msg_id,
        sender=source,
        intent="ping",
        repo=repo,
        pr=pr,
        branch=None,
        payload={
            "head_sha": head_sha,
            "source": source,
            "scheduled_for": scheduled_for or _default_scheduled_for(),
        },
        ts=ts.isoformat(),
        ledger=forward_ledger(incoming),
    )
    PING_INBOX.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(PING_INBOX, "a") as f:
            f.write(json.dumps(asdict(msg)) + "\n")
    except Exception as e:
        observe.event("ping_card_write_failed", repo=repo, pr=pr,
                      error_type=type(e).__name__, error=str(e)[:200])
        return None
    observe.event("ping_card_deposited", repo=repo, pr=pr,
                  head_sha=head_sha[:12], source=source, msg_id=msg_id)
    return await _signal_actor("ping", msg)


@activity.defn
async def ping_cycle(msg: Message) -> dict:
    """Check whether both signals have arrived for this (repo, pr,
    sha). If yes and not yet drafted: render the ping body, deposit on
    the human inbox, emit `ping_drafted`. If no: noop (the other
    signal hasn't landed yet; another kick will retry).
    """
    if not msg.repo or not msg.pr:
        raise ApplicationError(
            "ping: msg.repo + msg.pr required", non_retryable=True,
        )
    from sweep import observe
    head_sha = (msg.payload or {}).get("head_sha") or ""
    if not head_sha:
        raise ApplicationError(
            "ping: payload.head_sha required", non_retryable=True,
        )

    # Operator kill switch (shared with tissue/post). When set, refuse
    # to draft — draft accumulation while post is disabled defeats the
    # safety the flag exists for. Cleared via `rm ~/.sweep/control/
    # post_disabled`. Next ping kick re-evaluates fresh.
    if POST_DISABLED_FLAG.exists():
        observe.event("ping_skipped", repo=msg.repo, pr=msg.pr,
                      head_sha=head_sha[:12], reason="post_disabled",
                      msg_id=msg.msg_id)
        return {"status": "skipped", "reason": "post_disabled"}

    # Four deterministic preconditions, all file/gh ground truth:
    #   (a) post_disabled kill switch is NOT set (checked above)
    #   (b) attestation manifest exists for (repo, pr) pinned to this
    #       head_sha — substrate-side pass receipt
    #   (c) gh check-runs at this head_sha are all-green — maintainer
    #       CI agrees
    #   (d) we haven't already drafted a ping for this exact SHA
    # All required. Each is a file/api check, not event-log scanning —
    # so the gate is reproducible across worker restarts.
    if _already_drafted(msg.repo, int(msg.pr), head_sha):
        observe.event("ping_noop_already_drafted", repo=msg.repo,
                      pr=msg.pr, head_sha=head_sha[:12], msg_id=msg.msg_id)
        return {"status": "noop", "reason": "already_drafted"}

    has_attest = _attest_pass_for_sha(msg.repo, int(msg.pr), head_sha)
    total, passed, fail_or_pending = _gh_check_runs_for_sha(
        msg.repo, head_sha,
    )
    # Three CI states matter:
    #   (a) total > 0, all passed, none pending     → has_ci=True
    #   (b) total == 0                              → has_ci=True (no
    #       CI configured / maintainer-gated; nothing to wait for, so
    #       local attest is the only available ratification)
    #   (c) total > 0, any fail or pending          → has_ci=False
    # Treating (b) as wait would park first-time-contributor PRs
    # forever (most OSS repos gate `pull_request` workflows behind
    # maintainer approval). The ping message stays the same — the
    # maintainer can see their own CI status; what they're being
    # told is "I attested locally; here's the receipt."
    if total == 0:
        has_ci = True
        ci_status = "absent"
    elif passed > 0 and fail_or_pending == 0:
        has_ci = True
        ci_status = "all_green"
    else:
        has_ci = False
        ci_status = "in_progress_or_failing"

    if not (has_attest and has_ci):
        observe.event("ping_noop_waiting", repo=msg.repo, pr=msg.pr,
                      head_sha=head_sha[:12],
                      has_attest=has_attest, has_ci=has_ci,
                      ci_status=ci_status,
                      ci_passed=passed, ci_fail_or_pending=fail_or_pending,
                      msg_id=msg.msg_id)
        return {"status": "noop", "reason": "waiting",
                "has_attest": has_attest, "has_ci": has_ci,
                "ci_status": ci_status,
                "ci_passed": passed,
                "ci_fail_or_pending": fail_or_pending}

    body = _render_ping(msg.repo, int(msg.pr), head_sha,
                         ci_status=ci_status)
    # Deposit on human.jsonl with intent=ping-draft so the operator
    # surface (sweep inbox actor human / sweep ping list) shows it.
    ts = dt.datetime.now(dt.timezone.utc)
    draft = {
        "msg_id": f"ping-draft-{msg.repo.replace('/', '-')}-{msg.pr}-{head_sha[:12]}",
        "sender": "ping",
        "intent": "ping-draft",
        "repo": msg.repo,
        "pr": msg.pr,
        "branch": None,
        "payload": {
            "head_sha": head_sha,
            "body": body,
            "approve_cmd": (
                f"sweep ping approve --repo {msg.repo} --pr {msg.pr} "
                f"--head-sha {head_sha}"
            ),
        },
        "ts": ts.isoformat(),
        "ledger": [],
    }
    HUMAN_INBOX.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(HUMAN_INBOX, "a") as f:
            f.write(json.dumps(draft) + "\n")
    except Exception as e:
        raise ApplicationError(
            f"ping: failed to write human inbox: {e}", non_retryable=False,
        )
    _record_drafted(msg.repo, int(msg.pr), head_sha, draft["msg_id"])
    observe.event("ping_drafted", repo=msg.repo, pr=msg.pr,
                  head_sha=head_sha, msg_id=msg.msg_id,
                  draft_id=draft["msg_id"])
    return {"status": "drafted", "draft_id": draft["msg_id"],
            "head_sha": head_sha}


async def _scan_due_drafts_and_emit() -> dict:
    """Called by metronome on its hourly ping tick. Walks ping.jsonl,
    for each unique (repo, pr, sha) draft whose `scheduled_for` has
    passed AND that hasn't yet been recorded in PING_LEDGER:
      - re-runs deterministic precondition (attest manifest + gh CI)
      - emits the ping (writes draft to human inbox + records ledger)
    Skips drafts whose scheduled_for is in the future — they wait for
    a later hourly tick. Skips drafts already in the ledger.

    Honors post_disabled: if set, returns immediately without emitting.
    Drafts stay parked, scheduled_for re-checked next hour.
    """
    from sweep import observe
    if POST_DISABLED_FLAG.exists():
        observe.event("ping_scan_skipped_post_disabled")
        return {"checked": 0, "drafted": 0,
                "skipped_not_due": 0, "skipped_already_drafted": 0}
    if not PING_INBOX.exists():
        return {"checked": 0, "drafted": 0,
                "skipped_not_due": 0, "skipped_already_drafted": 0}

    now = dt.datetime.now(dt.timezone.utc)
    # Latest payload wins per (repo, pr, sha).
    latest: dict[tuple, dict] = {}
    for line in PING_INBOX.read_text().splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        payload = row.get("payload") or {}
        key = (row.get("repo"), row.get("pr"),
               payload.get("head_sha", ""))
        latest[key] = row

    checked = drafted = skipped_not_due = skipped_already = 0
    for (repo, pr, head_sha), row in latest.items():
        if not (repo and pr and head_sha):
            continue
        checked += 1
        if _already_drafted(repo, int(pr), head_sha):
            skipped_already += 1
            continue
        # scheduled_for gate
        payload = row.get("payload") or {}
        sched_s = payload.get("scheduled_for") or ""
        try:
            sched = dt.datetime.fromisoformat(sched_s) if sched_s else now
        except ValueError:
            sched = now
        if sched > now:
            skipped_not_due += 1
            continue
        # Preconditions
        if not _attest_pass_for_sha(repo, int(pr), head_sha):
            continue
        total, passed, fail_or_pending = _gh_check_runs_for_sha(repo, head_sha)
        if total == 0:
            ci_status = "absent"
            has_ci = True
        elif passed > 0 and fail_or_pending == 0:
            ci_status = "all_green"
            has_ci = True
        else:
            has_ci = False
            ci_status = "in_progress_or_failing"
        if not has_ci:
            continue
        # All preconditions met → draft + record.
        body = _render_ping(repo, int(pr), head_sha, ci_status=ci_status)
        ts = dt.datetime.now(dt.timezone.utc)
        draft = {
            "msg_id": f"ping-draft-{repo.replace('/', '-')}-{pr}-{head_sha[:12]}",
            "sender": "ping",
            "intent": "ping-draft",
            "repo": repo,
            "pr": pr,
            "branch": None,
            "payload": {
                "head_sha": head_sha,
                "body": body,
                "ci_status": ci_status,
                "approve_cmd": (
                    f"sweep ping approve --repo {repo} --pr {pr} "
                    f"--head-sha {head_sha}"
                ),
            },
            "ts": ts.isoformat(),
            "ledger": [],
        }
        HUMAN_INBOX.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(HUMAN_INBOX, "a") as f:
                f.write(json.dumps(draft) + "\n")
        except OSError as e:
            observe.event("ping_scan_write_failed", repo=repo, pr=pr,
                          error_type=type(e).__name__, error=str(e)[:200])
            continue
        _record_drafted(repo, int(pr), head_sha, draft["msg_id"])
        observe.event("ping_drafted", repo=repo, pr=pr,
                      head_sha=head_sha, draft_id=draft["msg_id"],
                      ci_status=ci_status, via="metronome_scan")
        drafted += 1
    return {
        "checked": checked,
        "drafted": drafted,
        "skipped_not_due": skipped_not_due,
        "skipped_already_drafted": skipped_already,
    }
