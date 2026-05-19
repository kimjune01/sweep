"""Sweep worker. Run with: uv run python -m sweep.worker

Requires a Temporal dev server running at localhost:7233.
Start one in another tab with: temporal server start-dev
"""

from __future__ import annotations

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from sweep.activities.pr_state import (
    classify_one_pr,
    deliver_to_inbox,
    deposit_classified,
    gh_pr_view,
    gh_search_open_authored,
    route_classified,
)
from sweep.activities.claim import claim_issue
from sweep.activities.infer import infer_test_cmd
from sweep.activities.sift import (
    auto_evict_stale_repos,
    loosen_floor,
    sift_cycle,
    sift_one_pass,
    should_triage_issue,
)
from sweep.activities.roll import roll_cycle
from sweep.activities.notifications import (
    mark_thread_read,
    poll_github_notifications,
)
from sweep.activities.skill_runner import respond_cycle, investigate_cycle, triage_cycle
from sweep.activities.remit import kick_remit_card, remit_cycle
from sweep.activities.submit import kick_submit_card, submit_cycle
from sweep.activities.compose import compose_cycle, kick_compose_card
from sweep.activities.reinvestigate import kick_reinvestigate_card, reinvestigate_cycle
from sweep.activities.reqa import kick_reqa_card, reqa_cycle
from sweep.activities.attest import attest_cycle, attest_pending_depth, kick_attest_card
from sweep.activities.amend import amend_cycle, kick_amend_card
from sweep.activities.check import (
    check_cycle, kick_check_card, kick_check_from_subject,
)
from sweep.activities.heart import heart_cycle, kick_heart_card
from sweep.activities.ping import kick_ping_card, ping_cycle
from sweep.activities.metronome import metronome_tick, kick_metronome_card
from sweep.activities.retro import retro_cycle, kick_retro_card
from sweep.activities.respond import kick_respond_card
from sweep.activities.rope import kick_rope_card, rope_cycle
from sweep.activities.bless import bless_cycle
from sweep.activities.bug_reporter import bug_reporter_cycle
from sweep.activities.immunize import immunize_cycle
from sweep.activities.comment_issue import comment_issue_cycle, post_cycle
from sweep.activities.file_issue import file_issue_cycle
from sweep.activities.switch import switch_cycle
from sweep.activities.sign import sign_cycle, kick_sign_card
from sweep.activities.usage_probe import probe_claude_usage
from sweep.activities.qa import (
    codex_review,
    extract_qa_verdicts,
    gemini_review,
    is_repo_evicted_activity,
    read_artifact_texts,
    test_attestation,
)
from sweep.activities.synth_test import synth_test_for_fix
from sweep.activities.worktree import (
    clear_andon_marker,
    ensure_worktree,
    mark_acked,
    mark_started,
    record_andon,
)
from sweep.activities.leakdog import leakdog_tick
from sweep.activities.pause_gate import should_idle
from sweep.workflows.leakdog import LeakdogDaemon
from sweep.workflows.notification_poller import NotificationPoller
from sweep.workflows.metronome_actor import MetronomeActor
from sweep.workflows.qa_actor import QaActor
from sweep.workflows.skill_actor import SkillActor
from sweep.workflows.usage_poller import UsagePoller

SWEEP_TASK_QUEUE = "sweep-tq"


async def _amain() -> None:
    logging.basicConfig(level=logging.INFO)
    client = await Client.connect("localhost:7233")
    worker = Worker(
        client,
        task_queue=SWEEP_TASK_QUEUE,
        workflows=[QaActor, SkillActor, MetronomeActor, UsagePoller, NotificationPoller, LeakdogDaemon],
        activities=[
            # qa
            test_attestation, codex_review, gemini_review,
            extract_qa_verdicts,
            read_artifact_texts,
            is_repo_evicted_activity,
            # synth_test — qa's test-writing step. Writer is shown the
            # issue + unfixed code only; fix diff hidden by design (see
            # memory/feedback_writer_naive_of_verifier.md).
            synth_test_for_fix,
            # inference + first-mover claim
            infer_test_cmd, claim_issue,
            # skill-shelling actors (respond + triage + investigate via SkillActor)
            respond_cycle, triage_cycle, investigate_cycle,
            # remit — router for raw PR-state cards. Adapter activity
            # around classify_one_pr + deliver_to_inbox; pulls the
            # classify-and-route loop out of NotificationPoller into
            # a first-class actor on the post-submit engagement cycle.
            remit_cycle, kick_remit_card,
            # submit — new-PR-create gate. Dry-mode hold lives at
            # pause_gate (cards pile in submit.jsonl while dry is on).
            # Skeleton: trusts upstream prep, delegates push to respond.
            submit_cycle, kick_submit_card,
            # compose — PR message writer between qa and submit.
            # Skeleton passthrough today; /compose skill upgrade lands
            # separately. First-class actor so the responsibility for
            # PR text is visible instead of buried in /drip --push.
            compose_cycle, kick_compose_card,
            # rope — pull-signal controller. Reads roll.jsonl depth,
            # fires roll if below target. Idle signals from downstream
            # actors trigger the tick; depth is the regulator. Kanban-
            # shaped: target is operator-tunable via
            # ~/.sweep/control/rope_target.
            rope_cycle, kick_rope_card,
            # reinvestigate + reqa — engagement-lane parallels to
            # investigate + qa. Same skills, different upstreams
            # (remit when maintainer_raised_concern or CI fails on an
            # existing PR), different downstream (skip compose/submit;
            # respond pushes to existing branch).
            reinvestigate_cycle, kick_reinvestigate_card,
            reqa_cycle, kick_reqa_card,
            # attest — behavioral gate split out of qa. Owns the
            # test_attestation step so qa's adversarial-review identity
            # doesn't tangle with "did the fix actually pass?" — same
            # principle as hiding the attestation from the producer.
            # Routes: pass→qa, fail+1st→investigate, fail+2nd→human.
            attest_cycle, kick_attest_card, attest_pending_depth,
            # amend — idempotent PR-description editor. Marker-wrapped
            # blocks per kind (attestation today; screenshots / sections
            # later); re-runs replace in place. Runs through dry mode
            # because `gh pr edit` is silent (no notifications).
            amend_cycle, kick_amend_card,
            # check — upstream CI watcher. Fetches /commits/{sha}/check-runs
            # and routes each failed check to remit so the post-submit
            # engagement loop picks it up. Mirrors GitHub's vocabulary;
            # distinct from `attest` (local belief) — `check` is the
            # external ratification CI provides.
            check_cycle, kick_check_card, kick_check_from_subject,
            # heart — periodic heartbeat fired by metronome. Cheap;
            # writes one line per beat to ~/.sweep/sweep-log/heart.jsonl
            # so cockpit / monitors / the operator can read "line is
            # alive" without inspecting actor depths.
            heart_cycle, kick_heart_card,
            # ping — both-greens correlator. Drafts a polite ping to
            # the maintainer when attest manifest pinned-SHA matches
            # gh check-runs all-green. Deterministic per-SHA
            # idempotency via ~/.sweep/control/ping_drafted.jsonl.
            ping_cycle, kick_ping_card,
            # metronome — cadence kicker. Self-timing actor (not a
            # daemon) that fires kick_<target>_card on schedule. retro
            # is the first cadence-driven target.
            metronome_tick, kick_metronome_card,
            # retro — backward pass. Triggered by metronome on cadence;
            # makes obvious fixes on its own and emits a human card per
            # pass summarizing auto_fixes + human_attended items.
            retro_cycle, kick_retro_card,
            # respond — push verbs. respond_cycle lives in skill_runner;
            # kick_respond_card is the actor-to-actor handoff helper.
            kick_respond_card,
            # comment-issue (drafts) + post (posts) — side-hatch on no-fix
            # investigations. comment-issue drafts, post posts; separation of
            # concerns means LLM hiccups and gh hiccups don't share an
            # andon.
            comment_issue_cycle, post_cycle,
            # file-issue (fresh-issue drafts) — sibling to comment-issue,
            # different output channel (`gh issue create`, not `gh issue
            # comment`). Posting handled inline by `sweep file-issue
            # approve`; results land in the hold-issue holding bin.
            file_issue_cycle,
            # switch — LLM classifier as an actor. Receives artifact
            # cards from investigate/reinvestigate, judges via Sonnet,
            # routes to qa / comment-issue / human. Replaces the inline
            # classifier in skill_runner; decouples LLM latency from
            # investigate's takt.
            switch_cycle,
            sign_cycle, kick_sign_card,
            # immunize — anti-AI repo routing (worth-pursuing decider
            # for slop-offer candidates). Receives from sift (two
            # branches) and triage.
            immunize_cycle,
            # bless — classifier-router for issue-comment responses.
            # Template-first, default human (LLM off in bootstrap).
            bless_cycle,
            # bug-reporter — classifies findings against the active PR's
            # diff. In-scope → compose (future wiring); adjacent → file-issue
            # (future wiring). Current first version: persists per-finding
            # decisions to bug-reporter-decisions.jsonl as a durable
            # artifact and emits bug_reporter_classified events. Downstream
            # routing wires up as a separate seam-change once the operator
            # sees real classifications and the failure shapes (andon /
            # operator overrides) inform the right adapter contract.
            bug_reporter_cycle,
            # usage probe
            probe_claude_usage,
            # roll (one search per card) + sift (one issue per card).
            # Per-card pacing replaces the old burst-per-pass model:
            # roll writes one sift card per raw issue; sift
            # screens one issue per fire, with should_idle between cards.
            roll_cycle,
            sift_cycle, should_triage_issue,
            loosen_floor, auto_evict_stale_repos,
            sift_one_pass,  # legacy star-cursor path, kept as escape hatch
            # worktree + cockpit view-layer markers
            ensure_worktree, mark_started, mark_acked,
            record_andon, clear_andon_marker,
            # remit-classify (PR-state classifier library used by remit)
            gh_search_open_authored, gh_pr_view, classify_one_pr,
            deposit_classified, route_classified, deliver_to_inbox,
            # notifications (push-shaped remit freshness)
            poll_github_notifications, mark_thread_read,
            # leakdog daemon (independent watchdog for resource leaks)
            leakdog_tick,
            # pause-gate: inbox-boundary check used by every actor's
            # main loop. Lets pause mean "no new starts" universally
            # instead of just sift.
            should_idle,
        ],
    )
    logging.info("worker up on task queue=%s", SWEEP_TASK_QUEUE)
    await worker.run()


def main() -> None:
    """Console-script entry. `sweep-worker` invokes this."""
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
