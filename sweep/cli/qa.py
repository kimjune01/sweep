"""`sweep qa …` — standalone activity invocations + Temporal QaActor controls."""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from dataclasses import asdict

import typer
from temporalio.client import Client

from sweep.activities.qa import (
    codex_review,
    gemini_review,
    qa_one_entry,
    test_attestation,
)
from sweep.cli._common import (
    QA_ACTOR_ID,
    SWEEP_TASK_QUEUE,
    build_req,
    git_diff,
    print_json,
)
from sweep.system import TEMPORAL_ADDR
from sweep.types import Message
from sweep.workflows.qa_actor import QaActor


qa_app = typer.Typer(help="QA pipeline activities", no_args_is_help=True)


@qa_app.command("test")
def qa_test(
    repo: str = typer.Option(..., help="owner/repo"),
    branch: str = typer.Option("", help="fix branch"),
    worktree: str = typer.Option(".", help="local clone path"),
    test_cmd: str = typer.Option("", help="test command, e.g. 'pytest -x'"),
    msg_id: str | None = typer.Option(None),
) -> None:
    """Run test_attestation only."""
    req = build_req(repo, branch, worktree, test_cmd, msg_id)
    print_json(asdict(asyncio.run(test_attestation(req))))


@qa_app.command("codex")
def qa_codex(
    repo: str = typer.Option(..., help="owner/repo"),
    branch: str = typer.Option("", help="fix branch"),
    worktree: str = typer.Option(".", help="local clone path"),
    msg_id: str | None = typer.Option(None),
) -> None:
    """Run codex_review only."""
    req = build_req(repo, branch, worktree, "", msg_id)
    print_json(asdict(asyncio.run(codex_review(req, git_diff(worktree)))))


@qa_app.command("gemini")
def qa_gemini(
    repo: str = typer.Option(..., help="owner/repo"),
    branch: str = typer.Option("", help="fix branch"),
    worktree: str = typer.Option(".", help="local clone path"),
    round: int = typer.Option(1, "--round", "-r"),
    msg_id: str | None = typer.Option(None),
) -> None:
    """Run gemini_review one round."""
    req = build_req(repo, branch, worktree, "", msg_id)
    print_json(asdict(asyncio.run(gemini_review(req, git_diff(worktree), round))))


@qa_app.command("full")
def qa_full(
    repo: str = typer.Option(..., help="owner/repo"),
    branch: str = typer.Option("", help="fix branch"),
    worktree: str = typer.Option(".", help="local clone path"),
    test_cmd: str = typer.Option("", help="test command"),
    msg_id: str | None = typer.Option(None),
) -> None:
    """Run qa_one_entry end-to-end (composer, no Temporal)."""
    req = build_req(repo, branch, worktree, test_cmd, msg_id)
    print_json(asdict(asyncio.run(qa_one_entry(req))))


# ----- Temporal QaActor controls

qa_actor_app = typer.Typer(help="Temporal QaActor controls", no_args_is_help=True)
qa_app.add_typer(qa_actor_app, name="actor")


async def _ensure_actor(client: Client) -> None:
    try:
        await client.start_workflow(
            QaActor.run, id=QA_ACTOR_ID, task_queue=SWEEP_TASK_QUEUE
        )
        print(f"started workflow {QA_ACTOR_ID}")
    except Exception as e:
        if "already started" in str(e).lower() or "AlreadyStartedError" in type(e).__name__:
            print(f"workflow {QA_ACTOR_ID} already running")
        else:
            raise


@qa_actor_app.command("signal")
def qa_actor_signal() -> None:
    """Signal QaActor with a synthetic message."""
    async def run() -> None:
        client = await Client.connect(TEMPORAL_ADDR)
        await _ensure_actor(client)
        handle = client.get_workflow_handle(QA_ACTOR_ID)
        msg = Message(
            msg_id=f"synthetic-{uuid.uuid4().hex[:8]}",
            sender="client",
            intent="reattest",
            repo="kimjune01/sweep",
            branch="temporal-pipeline",
            payload={"worktree": "/Users/junekim/Documents/sweep", "test_cmd": "echo synthetic"},
            ts=dt.datetime.now(dt.timezone.utc).isoformat(),
        )
        await handle.signal(QaActor.deliver, msg)
        print(f"signaled msg_id={msg.msg_id}")
    asyncio.run(run())


@qa_actor_app.command("drain")
def qa_actor_drain() -> None:
    """Signal QaActor with every unacked message in qa.jsonl.

    Recovery path for two scenarios:
      • Messages deposited before the actor existed (or signal wire
        landed); they're records but were never delivered.
      • Machine move: actor history wiped, file inbox still on disk.

    Idempotent — the actor dedupes by msg_id, so re-running is safe.
    """
    import json as _json
    from sweep.inbox_state import INBOX_DIR, load_msg_id_set
    from sweep.types import Message as _Msg

    async def run() -> None:
        path = INBOX_DIR / "qa.jsonl"
        if not path.exists():
            print("qa.jsonl missing — nothing to drain")
            return
        acked = load_msg_id_set(INBOX_DIR / "_acks.jsonl")
        client = await Client.connect(TEMPORAL_ADDR)
        await _ensure_actor(client)
        handle = client.get_workflow_handle(QA_ACTOR_ID)
        sent = skipped = 0
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                d = _json.loads(line)
            except _json.JSONDecodeError:
                continue
            mid = d.get("msg_id", "")
            if not mid or mid in acked:
                skipped += 1
                continue
            msg = _Msg(
                msg_id=mid,
                sender=d.get("sender", "drain"),
                intent=d.get("intent", "reattest"),
                repo=d.get("repo", ""),
                pr=d.get("pr"),
                branch=d.get("branch") or "",
                payload=d.get("payload", {}),
                ts=d.get("ts", dt.datetime.now(dt.timezone.utc).isoformat()),
            )
            await handle.signal(QaActor.deliver, msg)
            sent += 1
        print(f"drained: signaled={sent} skipped={skipped}")
    asyncio.run(run())


@qa_actor_app.command("status")
def qa_actor_status() -> None:
    """Query QaActor depth + halted."""
    async def run() -> None:
        client = await Client.connect(TEMPORAL_ADDR)
        handle = client.get_workflow_handle(QA_ACTOR_ID)
        print(await handle.query(QaActor.state))
    asyncio.run(run())


@qa_actor_app.command("clear")
def qa_actor_clear() -> None:
    """Clear andon halt."""
    async def run() -> None:
        client = await Client.connect(TEMPORAL_ADDR)
        handle = client.get_workflow_handle(QA_ACTOR_ID)
        await handle.signal(QaActor.clear_andon)
        print("clear_andon sent")
    asyncio.run(run())
