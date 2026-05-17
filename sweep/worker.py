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
from sweep.activities.scout import scout_cycle
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
from sweep.activities.attest import attest_cycle, kick_attest_card
from sweep.activities.metronome import metronome_tick, kick_metronome_card
from sweep.activities.retro import retro_cycle, kick_retro_card
from sweep.activities.respond import kick_respond_card
from sweep.activities.rope import kick_rope_card, rope_cycle
from sweep.activities.bless import bless_cycle
from sweep.activities.immunize import immunize_cycle
from sweep.activities.tissue import tissue_cycle, post_cycle
from sweep.activities.usage_probe import probe_claude_usage
from sweep.activities.qa import (
    codex_review,
    gemini_review,
    test_attestation,
)
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
            # rope — pull-signal controller. Reads scout.jsonl depth,
            # fires scout if below target. Idle signals from downstream
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
            attest_cycle, kick_attest_card,
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
            # tissue (drafts) + post (posts) — side-hatch on no-fix
            # investigations. tissue drafts, post posts; separation of
            # concerns means LLM hiccups and gh hiccups don't share an
            # andon.
            tissue_cycle, post_cycle,
            # immunize — anti-AI repo routing (worth-pursuing decider
            # for slop-offer candidates). Receives from sift (two
            # branches) and triage.
            immunize_cycle,
            # bless — classifier-router for issue-comment responses.
            # Template-first, default human (LLM off in bootstrap).
            bless_cycle,
            # usage probe
            probe_claude_usage,
            # scout (one search per card) + sift (one issue per card).
            # Per-card pacing replaces the old burst-per-pass model:
            # scout writes one sift card per raw issue; sift
            # screens one issue per fire, with should_idle between cards.
            scout_cycle,
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
