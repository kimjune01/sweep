"""Sweep worker. Run with: uv run python -m sweep.worker

Requires a Temporal dev server running at localhost:7233.
Start one in another tab with: temporal server start-dev
"""

from __future__ import annotations

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from sweep.activities.qa import (
    codex_review,
    gemini_review,
    qa_one_entry,
    test_attestation,
)
from sweep.workflows.qa_actor import QaActor

QA_TASK_QUEUE = "qa-tq"


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    client = await Client.connect("localhost:7233")
    worker = Worker(
        client,
        task_queue=QA_TASK_QUEUE,
        workflows=[QaActor],
        activities=[qa_one_entry, test_attestation, codex_review, gemini_review],
    )
    logging.info("worker up on task queue=%s", QA_TASK_QUEUE)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
