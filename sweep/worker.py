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
from sweep.activities.drip import drip_cycle
from sweep.activities.infer import infer_test_cmd
from sweep.activities.prospect import check_pull_conditions, prospect_one_pass
from sweep.activities.qa import (
    codex_review,
    gemini_review,
    test_attestation,
)
from sweep.activities.worktree import ensure_worktree, mark_acked, mark_started
from sweep.workflows.drip_actor import DripActor
from sweep.workflows.pr_state_workflow import PrStateWorkflow
from sweep.workflows.prospect_puller import ProspectPuller
from sweep.workflows.qa_actor import QaActor

SWEEP_TASK_QUEUE = "sweep-tq"


async def _amain() -> None:
    logging.basicConfig(level=logging.INFO)
    client = await Client.connect("localhost:7233")
    worker = Worker(
        client,
        task_queue=SWEEP_TASK_QUEUE,
        workflows=[QaActor, DripActor, PrStateWorkflow, ProspectPuller],
        activities=[
            # qa
            test_attestation, codex_review, gemini_review,
            # inference
            infer_test_cmd,
            # drip
            drip_cycle,
            # prospect puller
            prospect_one_pass, check_pull_conditions,
            # worktree + cockpit view-layer markers
            ensure_worktree, mark_started, mark_acked,
            # pr-state
            gh_search_open_authored, gh_pr_view, classify_one_pr,
            deposit_classified, route_classified, deliver_to_inbox,
        ],
    )
    logging.info("worker up on task queue=%s", SWEEP_TASK_QUEUE)
    await worker.run()


def main() -> None:
    """Console-script entry. `sweep-worker` invokes this."""
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
