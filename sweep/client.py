"""Sweep client. Drives Temporal workflows, runs activities in isolation,
inspects per-actor inboxes.

Temporal-mode (worker must be up + temporal server at :7233):
  uv run python -m sweep.client --synthetic            # signal QaActor
  uv run python -m sweep.client --state                # query QaActor
  uv run python -m sweep.client --clear-andon          # reset halted
  uv run python -m sweep.client --pr-state-workflow    # run PrStateWorkflow once

Standalone-activity (no worker, no server):
  uv run python -m sweep.client --test    --repo ... --branch ... --worktree . --test-cmd '…'
  uv run python -m sweep.client --codex   --repo ... --branch ... --worktree .
  uv run python -m sweep.client --gemini  --repo ... --branch ... --worktree . --round 1
  uv run python -m sweep.client --full    --repo ... --branch ... --worktree . --test-cmd '…'
  uv run python -m sweep.client --pr-state-classify --repo owner/repo --pr 123
  uv run python -m sweep.client --pr-state-run --limit 30

Inbox inspection (read-only, per-actor):
  uv run python -m sweep.client --inbox qa
  uv run python -m sweep.client --inbox drip
  uv run python -m sweep.client --inbox investigate
  uv run python -m sweep.client --inbox retro
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

from sweep.activities.pr_state import (
    classify_one_pr,
    deliver_to_inbox,
    gh_pr_view,
    gh_search_open_authored,
)
from sweep.activities.qa import (
    codex_review,
    gemini_review,
    qa_one_entry,
    test_attestation,
)
from sweep.types import Message, QaOneEntryRequest
from sweep.workflows.pr_state_workflow import PrStateWorkflow
from sweep.workflows.qa_actor import QaActor

SWEEP_TASK_QUEUE = "sweep-tq"
QA_ACTOR_ID = "qa-actor"


async def ensure_actor(client: Client) -> None:
    """Start QaActor if not already running. Idempotent on workflow_id."""
    try:
        await client.start_workflow(
            QaActor.run,
            id=QA_ACTOR_ID,
            task_queue=SWEEP_TASK_QUEUE,
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


def _inspect_inbox(actor: str) -> None:
    """Read ~/.sweep/inbox/<actor>.jsonl, dedupe by msg_id, print per-message
    summary. Each queue is independently inspectable — no need to grep across
    a shared log."""
    from pathlib import Path
    inbox = Path.home() / ".sweep" / "inbox" / f"{actor}.jsonl"
    if not inbox.exists():
        print(f"# {inbox} — no messages")
        return
    seen: dict[str, dict] = {}
    raw = 0
    for line in inbox.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        raw += 1
        try:
            m = json.loads(line)
        except json.JSONDecodeError:
            continue
        mid = m.get("msg_id")
        if mid:
            seen[mid] = m  # latest wins (file is append-only)

    acks = Path.home() / ".sweep" / "inbox" / "_acks.jsonl"
    acked: set[str] = set()
    if acks.exists():
        for line in acks.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                a = json.loads(line)
                if a.get("msg_id"):
                    acked.add(a["msg_id"])
            except json.JSONDecodeError:
                pass

    unacked = [m for mid, m in seen.items() if mid not in acked]
    acked_msgs = [m for mid, m in seen.items() if mid in acked]
    print(f"# {inbox}")
    print(f"# raw_lines={raw}  unique_msgs={len(seen)}  unacked={len(unacked)}  acked={len(acked_msgs)}")
    print()
    for m in sorted(unacked, key=lambda x: x.get("ts", "")):
        intent = m.get("intent", "?")
        repo = m.get("repo", "?")
        pr = m.get("pr") or "-"
        ts = m.get("ts", "")[:19]
        payload = m.get("payload") or {}
        reason = payload.get("reason", "")
        print(f"  [{ts}] {intent:9s} {repo}#{pr}  {reason}")


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
    g.add_argument("--pr-state-classify", action="store_true",
                   help="Standalone: classify ONE PR (needs --repo + --pr)")
    g.add_argument("--pr-state-run", action="store_true",
                   help="Standalone: classify ALL open PRs + deliver to inboxes")
    g.add_argument("--pr-state-workflow", action="store_true",
                   help="Temporal: run PrStateWorkflow once")
    g.add_argument("--inbox", metavar="ACTOR",
                   help="Inspect one inbox (qa | drip | investigate | retro). "
                        "Reads ~/.sweep/inbox/<ACTOR>.jsonl, dedupes by msg_id.")

    ap.add_argument("--repo", default="owner/repo")
    ap.add_argument("--branch", default="branch")
    ap.add_argument("--worktree", default=".")
    ap.add_argument("--test-cmd", default="")
    ap.add_argument("--msg-id", default=None)
    ap.add_argument("--issue", type=int, default=None)
    ap.add_argument("--round", type=int, default=1)
    ap.add_argument("--pr", type=int, default=None, help="PR number for --pr-state-classify")
    ap.add_argument("--limit", type=int, default=50, help="Max PRs for --pr-state-run")

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
    if args.pr_state_classify:
        if not args.pr:
            ap.error("--pr-state-classify requires --pr N --repo owner/repo")
        state = await gh_pr_view(args.repo, args.pr)
        result = await classify_one_pr(state)
        print(json.dumps(asdict(result), indent=2))
        return
    if args.inbox:
        _inspect_inbox(args.inbox)
        return
    if args.pr_state_run:
        prs = await gh_search_open_authored(args.limit)
        print(f"# {len(prs)} open PRs")
        for raw in prs:
            repo = raw["repository"]["nameWithOwner"]
            pr = raw["number"]
            try:
                state = await gh_pr_view(repo, pr)
                result = await classify_one_pr(state)
                path = await deliver_to_inbox(result)
                print(f"  {repo}#{pr} → {result.bucket} ({result.reason}) → {path}")
            except Exception as e:
                print(f"  {repo}#{pr} → ERROR: {e}")
        return

    client = await Client.connect("localhost:7233")
    if args.synthetic:
        await synthetic(client)
    elif args.state:
        await state(client)
    elif args.clear_andon:
        await clear_andon(client)
    elif args.pr_state_workflow:
        import uuid as _uuid
        result = await client.execute_workflow(
            PrStateWorkflow.run,
            args.limit,
            id=f"pr-state-{_uuid.uuid4().hex[:8]}",
            task_queue=SWEEP_TASK_QUEUE,
        )
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
