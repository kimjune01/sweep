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
from sweep.activities.prospect import (
    auto_evict_stale_repos,
    loosen_floor,
    prospect_cycle,
    prospect_one_pass,
    should_triage_issue,
)
from sweep.activities.scout import scout_cycle
from sweep.activities.notifications import (
    mark_thread_read,
    poll_github_notifications,
)
from sweep.activities.skill_runner import drip_cycle, investigate_cycle, triage_cycle
from sweep.activities.bless import bless_cycle
from sweep.activities.immunize import immunize_cycle
from sweep.activities.tissue import tissue_cycle, wipe_cycle
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
from sweep.workflows.pr_state_workflow import PrStateWorkflow
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
        workflows=[QaActor, SkillActor, PrStateWorkflow, UsagePoller, NotificationPoller, LeakdogDaemon],
        activities=[
            # qa
            test_attestation, codex_review, gemini_review,
            # inference + first-mover claim
            infer_test_cmd, claim_issue,
            # skill-shelling actors (drip + triage + investigate via SkillActor)
            drip_cycle, triage_cycle, investigate_cycle,
            # tissue (drafts) + wipe (posts) — side-hatch on no-fix
            # investigations. tissue drafts, wipe posts; separation of
            # concerns means LLM hiccups and gh hiccups don't share an
            # andon.
            tissue_cycle, wipe_cycle,
            # immunize — anti-AI repo routing (worth-pursuing decider
            # for slop-offer candidates). Receives from prospect (two
            # branches) and triage.
            immunize_cycle,
            # bless — classifier-router for issue-comment responses.
            # Template-first, default human (LLM off in bootstrap).
            bless_cycle,
            # usage probe
            probe_claude_usage,
            # scout (one search per card) + prospect (one issue per card).
            # Per-card pacing replaces the old burst-per-pass model:
            # scout writes one prospect card per raw issue; prospect
            # screens one issue per fire, with should_idle between cards.
            scout_cycle,
            prospect_cycle, should_triage_issue,
            loosen_floor, auto_evict_stale_repos,
            prospect_one_pass,  # legacy star-cursor path, kept as escape hatch
            # worktree + cockpit view-layer markers
            ensure_worktree, mark_started, mark_acked,
            record_andon, clear_andon_marker,
            # pr-state
            gh_search_open_authored, gh_pr_view, classify_one_pr,
            deposit_classified, route_classified, deliver_to_inbox,
            # notifications (push-shaped pr-state freshness)
            poll_github_notifications, mark_thread_read,
            # leakdog daemon (independent watchdog for resource leaks)
            leakdog_tick,
            # pause-gate: inbox-boundary check used by every actor's
            # main loop. Lets pause mean "no new starts" universally
            # instead of just prospect.
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
