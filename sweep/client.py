"""Sweep client. Examples of starting workflows + signaling actors.

Usage:
  uv run python -m sweep.client --synthetic       # send a fake msg to QaActor
  uv run python -m sweep.client --state           # query QaActor's depth + halted
  uv run python -m sweep.client --clear-andon     # reset the halted flag

Requires the worker (sweep.worker) to be running and the Temporal dev server
up at localhost:7233.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import uuid

from temporalio.client import Client

from sweep.types import Message
from sweep.workflows.qa_actor import QaActor

QA_TASK_QUEUE = "qa-tq"
QA_ACTOR_ID = "qa-actor"


async def ensure_actor(client: Client) -> None:
    """Start QaActor if not already running. Idempotent on workflow_id."""
    try:
        await client.start_workflow(
            QaActor.run,
            id=QA_ACTOR_ID,
            task_queue=QA_TASK_QUEUE,
        )
        print(f"started workflow {QA_ACTOR_ID}")
    except Exception as e:
        if "already started" in str(e).lower() or "WorkflowExecutionAlreadyStartedError" in type(e).__name__:
            print(f"workflow {QA_ACTOR_ID} already running")
        else:
            raise


async def synthetic(client: Client) -> None:
    await ensure_actor(client)
    handle = client.get_workflow_handle(QA_ACTOR_ID)
    msg = Message(
        msg_id=f"synthetic-{uuid.uuid4().hex[:8]}",
        sender="client",
        intent="reattest",
        repo="kimjune01/sweep",
        branch="temporal-pipeline",
        payload={
            "worktree": "/Users/junekim/Documents/sweep",
            "test_cmd": "echo synthetic",
        },
        ts=dt.datetime.now(dt.timezone.utc).isoformat(),
    )
    await handle.signal(QaActor.deliver, msg)
    print(f"signaled msg_id={msg.msg_id}")


async def state(client: Client) -> None:
    handle = client.get_workflow_handle(QA_ACTOR_ID)
    s = await handle.query(QaActor.state)
    print(s)


async def clear_andon(client: Client) -> None:
    handle = client.get_workflow_handle(QA_ACTOR_ID)
    await handle.signal(QaActor.clear_andon)
    print("clear_andon sent")


async def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--synthetic", action="store_true")
    g.add_argument("--state", action="store_true")
    g.add_argument("--clear-andon", action="store_true")
    args = ap.parse_args()

    client = await Client.connect("localhost:7233")
    if args.synthetic:
        await synthetic(client)
    elif args.state:
        await state(client)
    elif args.clear_andon:
        await clear_andon(client)


if __name__ == "__main__":
    asyncio.run(main())
