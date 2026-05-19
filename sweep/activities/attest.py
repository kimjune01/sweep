"""Attest — behavioral verification, downstream of qa.

Runs the test-attestation gate (fail-on-master, pass-on-fix) and routes
the card based on outcome:

  pass         → compose.jsonl (with attestation_hash payload; compose
                 requires the hash as a precondition before it'll write
                 the PR body). Also fans out to amend.jsonl when msg.pr
                 is set, so the maintainer-visible PR body picks up the
                 triple-link footer.
  fail, 1st    → reinvestigate.jsonl (if msg.pr) or investigate.jsonl
                 (forward lane) — same skill either side, lane chosen
                 by whether a PR already exists.
  fail, 2nd+   → andon (raise non_retryable). Two failed passes is a
                 substrate signal; halting forces an operator look
                 instead of silently piling cards into human.jsonl.

"1st vs 2nd" is read from the card's ledger: `msg.ledger.count("attest")`.
First time attest sees a card, the ledger has no "attest"; second
time, it does. No separate counter, no cross-inbox reads.

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

from sweep.types import Message, QaOneEntryRequest, forward_ledger


ATTEST_INBOX = Path.home() / ".sweep" / "inbox" / "attest.jsonl"
COMPOSE_INBOX = Path.home() / ".sweep" / "inbox" / "compose.jsonl"
INVESTIGATE_INBOX = Path.home() / ".sweep" / "inbox" / "investigate.jsonl"
REINVESTIGATE_INBOX = Path.home() / ".sweep" / "inbox" / "reinvestigate.jsonl"


def _append(inbox: Path, msg: Message) -> None:
    inbox.parent.mkdir(parents=True, exist_ok=True)
    with open(inbox, "a") as f:
        f.write(json.dumps(asdict(msg)) + "\n")


@activity.defn
async def attest_pending_depth() -> int:
    """Return attest-actor's pending-queue depth. Read via Temporal
    workflow query so we see the real in-memory queue, not the
    append-only inbox.jsonl (which counts processed cards too).

    Used by qa-actor as a pull-shaped backpressure check: don't dispatch
    the next qa card when attest is already saturated. The pull-from-
    downstream shape is the kanban primitive — same as rope→scout, just
    one interface downstream.

    Returns 0 on any error (query timeout, attest-actor missing,
    temporal unreachable). Fail-open is correct here: a failed query
    shouldn't strand qa, and a temporary over-pull is recoverable; an
    incorrect halt isn't.
    """
    try:
        from temporalio.client import Client
        from sweep.system import TEMPORAL_ADDR
        from sweep.cli._common import ATTEST_ACTOR_ID
        client = await Client.connect(TEMPORAL_ADDR)
        handle = client.get_workflow_handle(ATTEST_ACTOR_ID)
        state = await handle.query("state")
        if isinstance(state, dict):
            return int(state.get("depth", 0))
        return 0
    except Exception:
        return 0


@activity.defn
async def kick_attest_card(repo: str, branch: str,
                           pr: int | None = None,
                           sender: str = "investigate",
                           incoming: Message | None = None,
                           payload: dict | None = None) -> str | None:
    """Deposit an attest card on attest.jsonl and signal attest-actor.

    Caller passes `incoming=msg` when forwarding from inside an
    activity processing `msg`; the ledger extends automatically.
    Origin callers pass nothing → ledger=[].
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
        ledger=forward_ledger(incoming),
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
        ledger=forward_ledger(msg),
    )
    _append(inbox, out)
    return out


def _route_pass(msg: Message, attestation_hash: str,
                attestation_links_md: str | None = None) -> Message:
    """Pass routes to compose. attest is now downstream of qa, so by
    the time a card lands `pass` here, qa has already reviewed (and
    possibly edited) the branch. Compose writes the PR body, gated on
    the attestation_hash we carry here."""
    extra = {"attestation_hash": attestation_hash}
    if attestation_links_md:
        extra["attestation_links_md"] = attestation_links_md
    return _emit(COMPOSE_INBOX, msg, kind="compose", extra_payload=extra)


def _route_retry(msg: Message, reason: str) -> Message:
    """Route the first-look fail back to the right lane.

    A card with msg.pr already on it came in via the engagement lane
    (a PR exists; remit / reqa / amend live here), so its retry goes
    to reinvestigate. A card without a PR came in via the forward
    lane (pre-submit investigate → qa → submit), so its retry goes
    back to investigate. Same skill either side; the lane choice is
    about which downstream actor expects this shape next.
    """
    if msg.pr:
        return _emit(REINVESTIGATE_INBOX, msg, kind="reinvestigate",
                     extra_payload={"attest_failure_reason": reason[-2000:]})
    return _emit(INVESTIGATE_INBOX, msg, kind="investigate",
                 extra_payload={"attest_failure_reason": reason[-2000:]})


def _publish_attestation(*, req: QaOneEntryRequest, msg_id: str) -> str | None:
    """Move qa's local attestation triple to a public, linkable state:
    git add → commit → push → render pinned-SHA snippet. Each step
    gates the next; first failure returns None so amend never receives
    a dead URL. The triple stays on disk regardless.

    Inverse of qa's responsibility: qa runs the tests and writes the
    files; attest publishes them. The path-derivation here mirrors qa's
    exactly because both ends need to agree on which files belong to
    this attestation — small duplication, big simplification (no extra
    handoff field on GateAttestation).
    """
    import subprocess
    from pathlib import Path

    from sweep import observe
    from sweep.attestation_writer import render_attestation_links_md

    sweep_repo = Path(__file__).resolve().parent.parent.parent
    org_repo = req.repo.replace("/", "-")
    issue_key = req.issue or req.branch.removeprefix("fix/").replace("/", "__")
    attestation_name = f"issue-{issue_key}"
    rel = f"attestations/{org_repo}"

    add = subprocess.run(
        ["git", "-C", str(sweep_repo), "add", rel],
        capture_output=True, text=True, timeout=10,
    )
    if add.returncode != 0:
        observe.event("attestation_add_failed", msg_id=msg_id,
                      repo=req.repo, stderr=(add.stderr or "")[:300])
        return None

    cmt = subprocess.run(
        ["git", "-C", str(sweep_repo), "commit", "-m",
         f"attestation: {org_repo}/{attestation_name}"],
        capture_output=True, text=True, timeout=10,
    )
    if cmt.returncode != 0:
        observe.event("attestation_commit_failed", msg_id=msg_id,
                      repo=req.repo, stderr=(cmt.stderr or "")[:300])
        return None
    observe.event("attestation_committed", msg_id=msg_id,
                  repo=req.repo, branch=req.branch)

    push = subprocess.run(
        ["git", "-C", str(sweep_repo), "push", "origin", "HEAD"],
        capture_output=True, text=True, timeout=30,
    )
    if push.returncode != 0:
        observe.event("attestation_push_failed", msg_id=msg_id,
                      repo=req.repo, stderr=(push.stderr or "")[:300])
        return None
    observe.event("attestation_published", msg_id=msg_id, repo=req.repo)

    sha_p = subprocess.run(
        ["git", "-C", str(sweep_repo), "rev-parse", "HEAD"],
        capture_output=True, text=True, timeout=5,
    )
    remote_p = subprocess.run(
        ["git", "-C", str(sweep_repo), "config", "--get", "remote.origin.url"],
        capture_output=True, text=True, timeout=5,
    )
    if sha_p.returncode != 0 or remote_p.returncode != 0:
        return None
    return render_attestation_links_md(
        remote_url=remote_p.stdout.strip(),
        commit_sha=sha_p.stdout.strip(),
        org_repo=org_repo,
        name=attestation_name,
        has_before=True,
    )


@activity.defn
async def attest_cycle(msg: Message) -> dict:
    """Run test_attestation; route by verdict + kanban position.

    Verdict routing:
      pass             → qa (+ amend fan-out if msg.pr set)
      fail, 1st look   → reinvestigate (if msg.pr) or investigate
                         (the right re-diagnose lane for this card's stage)
      fail, 2nd look   → andon (raise non_retryable). Two failed passes
                         is a substrate signal — quietly stacking cards
                         into human.jsonl hides it; halting forces an
                         operator look. `sweep andon clear` resumes.

    Other ApplicationErrors (missing toolchain, test_passes_on_master,
    git checkout failure) propagate and halt the actor.
    """
    from sweep import observe
    from sweep.activities.qa import test_attestation
    from sweep.activities.worktree import ensure_worktree
    from sweep.activities.infer import infer_test_cmd

    if not msg.repo or not msg.branch:
        raise ApplicationError(
            "attest: msg.repo and msg.branch required", non_retryable=True,
        )

    # Short-circuit cards for evicted repos. Operator marked the repo
    # out-of-rotation; any in-flight card from before the eviction
    # should noop instead of burning a cycle. This is the activity-
    # entry guarantee that complements the inbox-jsonl-level flush.
    from sweep.activities.qa import is_repo_evicted
    if is_repo_evicted(msg.repo):
        from sweep import observe
        observe.event("evicted_skip", actor="attest_cycle",
                      repo=msg.repo, msg_id=msg.msg_id)
        return {"verdict": "skip", "target": "sink",
                "reason": "repo_evicted", "msg_id": msg.msg_id}

    # Front-load the draft check: attesting a draft is wasted work in
    # both directions — the operator has explicitly parked the PR, and
    # the amend fan-out's footer splice would land on a body the
    # operator may not want noised. Skip with a recorded verdict so the
    # ledger shows we noticed and chose not to test. Same shape as the
    # `ci_regressions` skip above wild#1924 used.
    if msg.pr:
        from sweep import gh_io
        try:
            pr_data = gh_io.pr_view(msg.repo, int(msg.pr), ttl=60)
            if pr_data.get("isDraft"):
                from sweep import observe
                observe.event(
                    "attest_routed", repo=msg.repo, branch=msg.branch,
                    verdict="skip", target="sink",
                    reason="pr_is_draft", msg_id=msg.msg_id,
                )
                return {"verdict": "skip", "reason": "pr_is_draft",
                        "target": "sink"}
        except Exception:
            # Best-effort precheck — if the gh fetch fails for any
            # reason, fall through to the normal path rather than
            # block the card. The downstream env check will catch
            # repo-level issues.
            pass

    # Front-load: if real CI is already green, skip attest. The
    # maintainer's CI is the authority — they trust it more than our
    # sweep-tester:latest model anyway. Local attest is for the case
    # where CI is red/missing AND we want to prove the fix works
    # without waiting on their pipeline. Real-green-then-local-attest
    # is wasted work; emit a routed=skip event so the trail shows we
    # noticed and chose not to re-verify.
    if msg.pr:
        from sweep import gh_io
        try:
            checks = gh_io.pr_failing_checks(msg.repo, int(msg.pr), ttl=60)
            # pr_failing_checks returns {} or a dict with failing counts.
            # Empty (no failing) + at least one check having run is the
            # "CI green" signal. If checks haven't been fetched / no
            # workflows exist, fall through to local attest.
            if isinstance(checks, dict):
                failing = checks.get("failing") or []
                total = int(checks.get("total", 0))
                if not failing and total > 0:
                    from sweep import observe
                    observe.event(
                        "attest_routed", repo=msg.repo, branch=msg.branch,
                        verdict="skip", target="ci-green",
                        reason=f"ci_green:{total}_checks_passed",
                        msg_id=msg.msg_id,
                    )
                    return {"verdict": "skip", "target": "ci-green",
                            "reason": "ci_green",
                            "checks_passed": total}
        except Exception:
            # Best-effort: if gh fetch fails, fall through to local
            # attest. Same posture as the draft check above.
            pass

    # Front-load the env precondition: if the test env this repo
    # requires isn't possible on this host (docker missing, image
    # un-pullable, image arch ≠ host arch under qemu), bail BEFORE
    # any verification work. A misattributed env failure inside
    # test_attestation would look like "fix is broken" downstream
    # and route us into a re-investigate loop on a sound patch.
    from sweep.activities.qa import assert_test_env_available
    assert_test_env_available(msg.repo)

    # Honor an operator-supplied worktree on the payload. Useful when
    # the fix branch lives on a fork the substrate's clone can't reach
    # (e.g. PR head on a contributor fork), or when the operator
    # already has the branch checked out locally. The provided path
    # must have the fix branch + default branch available; test cycle
    # just `git checkout`s into them.
    payload_wt = (msg.payload or {}).get("worktree")
    from pathlib import Path
    if payload_wt and Path(payload_wt).is_dir():
        worktree = str(payload_wt)
    else:
        worktree = await ensure_worktree(msg.repo, msg.branch,
                                         int(msg.pr) if msg.pr else None)
    test_cmd = await infer_test_cmd(worktree, msg.repo)
    if not test_cmd:
        # infer_test_cmd returned empty — no test convention detected
        # for this repo. Skip the attestation cycle cleanly; no andon,
        # no wasted test_attestation call. Operator can override via
        # `sweep retro set --repo X --key test_cmd --value '...'` if
        # the model missed something.
        from sweep import observe
        observe.event(
            "attest_routed", repo=msg.repo, branch=msg.branch,
            verdict="skip", target="no-test-cmd",
            reason="infer_test_cmd_returned_empty", msg_id=msg.msg_id,
        )
        return {"verdict": "skip", "target": "no-test-cmd",
                "reason": "no_test_cmd_detected"}
    req = QaOneEntryRequest(
        msg_id=msg.msg_id,
        repo=msg.repo,
        branch=msg.branch,
        worktree=worktree,
        test_cmd=test_cmd,
        issue=int(msg.pr) if msg.pr else 0,
    )

    second_look = msg.ledger.count("attest") >= 1

    try:
        att = await test_attestation(req)
    except ApplicationError as e:
        reason = str(e.message or "")
        # `no_tests_in_pr` is a per-PR finding ("this PR can't be
        # attested until tests are written"), not a substrate failure.
        # Route it as a `skip`-class verdict to the sink so the line
        # keeps moving; the remediation prompt CLI surfaces it for
        # operator attention without halting the actor.
        if "no_tests_in_pr" in reason:
            from sweep.activities.pr_state import _sink_pr
            if msg.pr:
                _sink_pr(msg.repo, int(msg.pr),
                         reason=f"no_tests_in_pr: {reason[:200]}",
                         state="OPEN_UNVERIFIABLE")
            observe.event(
                "attest_routed", repo=msg.repo, branch=msg.branch,
                verdict="skip", target="sink", reason="no_tests_in_pr",
                msg_id=msg.msg_id,
            )
            return {"verdict": "skip", "target": "sink",
                    "reason": "no_tests_in_pr",
                    "msg_id": msg.msg_id}
        # `test_passes_on_master` is the upstream-already-fixed signal.
        # Bug got fixed before our PR landed; the test added here
        # passes on master too. Quick close — substrate has
        # authoritative grounds (it just ran the test on master and
        # got exit 0), no maintainer decision needed. Same non-halt
        # routing as no_tests_in_pr: sink + verdict event + return.
        # The next `sweep evict process-sink` self-closes via the
        # `_should_self_close` rule.
        if "test_passes_on_master" in reason:
            from sweep.activities.pr_state import _sink_pr
            if msg.pr:
                _sink_pr(msg.repo, int(msg.pr),
                         reason=f"test_passes_on_master: {reason[:200]}",
                         state="OPEN_OBSOLETE")
            observe.event(
                "attest_routed", repo=msg.repo, branch=msg.branch,
                verdict="skip", target="sink",
                reason="test_passes_on_master",
                msg_id=msg.msg_id,
            )
            return {"verdict": "skip", "target": "sink",
                    "reason": "test_passes_on_master",
                    "msg_id": msg.msg_id}
        # "test_fails_on_fix" is a genuine, routable verdict, not
        # broken substrate. Everything else (toolchain missing, master
        # passing, git checkout failure) propagates to halt the actor.
        if "test_fails_on_fix" not in reason:
            raise

        # Second-look fail = the fix lane was given two chances and
        # neither passed. That's substrate behavior the line shouldn't
        # paper over by quietly dropping cards into human.jsonl —
        # surface it via andon so the operator decides. Raising
        # non_retryable triggers SkillActor's exception handler →
        # record_andon → halted=True until `sweep andon clear`.
        if second_look:
            observe.event(
                "attest_routed", repo=msg.repo, branch=msg.branch,
                verdict="fail", target="andon", second_look=True,
                msg_id=msg.msg_id,
            )
            raise ApplicationError(
                f"test_fails_on_fix on second look ({msg.repo}@{msg.branch}): "
                f"{reason[:200]}",
                non_retryable=True,
            )

        # First-look fail: route back to the right lane for another
        # pass. Same shape as before, lane chosen by msg.pr.
        _route_retry(msg, reason)
        target = "reinvestigate" if msg.pr else "investigate"
        observe.event(
            "attest_routed", repo=msg.repo, branch=msg.branch,
            verdict="fail", target=target, second_look=False,
            msg_id=msg.msg_id,
        )
        return {
            "verdict": "fail",
            "target": target,
            "second_look": False,
            "msg_id": msg.msg_id,
        }

    # Publish step: qa wrote the triple into our sweep working tree;
    # attest is responsible for getting it from "files on disk" to
    # "live URLs in the maintainer's PR body." Three sub-steps —
    # commit, push, render — each gated on the previous succeeding.
    # On any failure we drop the snippet so amend never receives a
    # dead URL. The local files stay; a future run / manual push can
    # surface them later.
    links_md = _publish_attestation(req=req, msg_id=msg.msg_id)

    _route_pass(msg, attestation_hash=att.sha256,
                attestation_links_md=links_md)

    # Fan out to amend so the maintainer-visible PR body picks up the
    # triple-link footer. Idempotent at amend; noop if no PR exists yet
    # (so attest-before-submit still works without coordination).
    if msg.pr and links_md:
        from sweep.activities.amend import kick_amend_card
        await kick_amend_card(
            repo=msg.repo, pr=int(msg.pr), kind="attestation",
            sender="attest", incoming=msg,
            payload={"attestation_links_md": links_md},
        )

    # Fan out to ping so the both-greens correlator gets the
    # substrate-side signal. The ping actor checks gh CI state
    # independently before drafting — this kick just announces "we
    # passed at SHA X; if maintainer-CI is also green for X, ping is
    # earned." Pinned head_sha comes from `att.pinned_head_sha`
    # (captured at test-attestation time in _capture).
    head_sha = getattr(att, "pinned_head_sha", None) or ""
    if msg.pr and head_sha:
        from sweep.activities.ping import kick_ping_card
        await kick_ping_card(
            repo=msg.repo, pr=int(msg.pr), head_sha=head_sha,
            source="attest", incoming=msg,
        )
    observe.event(
        "attest_routed", repo=msg.repo, branch=msg.branch,
        verdict="pass", target="compose", attestation_hash=att.sha256,
        msg_id=msg.msg_id,
    )
    return {
        "verdict": "pass",
        "target": "compose",
        "attestation_hash": att.sha256,
        "msg_id": msg.msg_id,
    }
