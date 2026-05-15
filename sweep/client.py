"""Sweep client. Examples of starting workflows + signaling actors AND
running individual activities in isolation for development.

Temporal-mode usage (worker must be up + temporal server at :7233):
  uv run python -m sweep.client --synthetic
  uv run python -m sweep.client --state
  uv run python -m sweep.client --clear-andon

Standalone-activity mode (no worker, no server — for iterating on one
activity in isolation):
  uv run python -m sweep.client --test --repo owner/repo --branch foo --worktree . --test-cmd 'pytest -x'
  uv run python -m sweep.client --codex --repo owner/repo --branch foo --worktree .
  uv run python -m sweep.client --gemini --repo owner/repo --branch foo --worktree . --round 1
  uv run python -m sweep.client --full --repo owner/repo --branch foo --worktree . --test-cmd 'pytest -x'
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import subprocess
import uuid
from dataclasses import asdict

from temporalio.client import Client

from sweep.activities.qa import (
    codex_review,
    gemini_review,
    qa_one_entry,
    test_attestation,
)
from sweep.types import Message, QaOneEntryRequest
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


def _build_req(args: argparse.Namespace) -> QaOneEntryRequest:
    return QaOneEntryRequest(
        msg_id=args.msg_id or f"dev-{uuid.uuid4().hex[:8]}",
        repo=args.repo,
        branch=args.branch,
        worktree=args.worktree,
        test_cmd=args.test_cmd or "",
        issue=args.issue,
    )


def _diff(worktree: str) -> str:
    return subprocess.run(
        ["git", "-C", worktree, "diff", "origin/HEAD..."],
        capture_output=True, text=True,
    ).stdout


async def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--synthetic", action="store_true",
                   help="Temporal: signal QaActor with a fake message")
    g.add_argument("--state", action="store_true",
                   help="Temporal: query QaActor depth + halted")
    g.add_argument("--clear-andon", action="store_true",
                   help="Temporal: reset halted flag")
    g.add_argument("--test", action="store_true",
                   help="Standalone: run test_attestation only")
    g.add_argument("--codex", action="store_true",
                   help="Standalone: run codex_review only")
    g.add_argument("--gemini", action="store_true",
                   help="Standalone: run one gemini_review round")
    g.add_argument("--full", action="store_true",
                   help="Standalone: run qa_one_entry end-to-end")

    ap.add_argument("--repo", default="owner/repo")
    ap.add_argument("--branch", default="branch")
    ap.add_argument("--worktree", default=".")
    ap.add_argument("--test-cmd", default="")
    ap.add_argument("--msg-id", default=None)
    ap.add_argument("--issue", type=int, default=None)
    ap.add_argument("--round", type=int, default=1)

    args = ap.parse_args()

    # Standalone activity invocations — no Temporal needed.
    if args.test:
        out = await test_attestation(_build_req(args))
        print(json.dumps(asdict(out), indent=2))
        return
    if args.codex:
        out = await codex_review(_build_req(args), _diff(args.worktree))
        print(json.dumps(asdict(out), indent=2))
        return
    if args.gemini:
        out = await gemini_review(_build_req(args), _diff(args.worktree), args.round)
        print(json.dumps(asdict(out), indent=2))
        return
    if args.full:
        out = await qa_one_entry(_build_req(args))
        print(json.dumps(asdict(out), indent=2, default=str))
        return

    client = await Client.connect("localhost:7233")
    if args.synthetic:
        await synthetic(client)
    elif args.state:
        await state(client)
    elif args.clear_andon:
        await clear_andon(client)


if __name__ == "__main__":
    asyncio.run(main())
