"""`sweep pr-state …` — classify / run / scan / route / workflow.

  classify   one PR (read-only)
  run        all open PRs → deliver_to_inbox (legacy coupled path)
  scan       all open PRs → classified.jsonl (decoupled half 1)
  route      classified.jsonl → per-actor inboxes (decoupled half 2)
  workflow   Temporal: PrStateWorkflow once
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import asdict

import typer
from temporalio.client import Client

from sweep.activities.pr_state import (
    classify_one_pr,
    deliver_to_inbox,
    deposit_classified,
    gh_pr_view,
    gh_search_open_authored,
    route_classified,
)
from sweep.cli._common import SWEEP_TASK_QUEUE, print_json
from sweep.system import TEMPORAL_ADDR
from sweep.workflows.pr_state_workflow import PrStateWorkflow


pr_state_app = typer.Typer(help="PR-state classifier + dispatcher", no_args_is_help=True)


@pr_state_app.command("classify")
def pr_state_classify(
    repo: str = typer.Option(..., help="owner/repo"),
    pr: int = typer.Option(..., help="PR number"),
) -> None:
    """Classify ONE PR (read-only)."""
    async def run() -> None:
        state = await gh_pr_view(repo, pr)
        result = await classify_one_pr(state)
        print_json(asdict(result))
    asyncio.run(run())


@pr_state_app.command("run")
def pr_state_run(
    limit: int = typer.Option(50, help="max PRs to classify"),
) -> None:
    """Classify all open PRs and deliver one message per PR to its inbox."""
    async def run() -> None:
        prs = await gh_search_open_authored(limit)
        print(f"# {len(prs)} open PRs")
        for raw in prs:
            r = raw["repository"]["nameWithOwner"]
            n = raw["number"]
            try:
                state = await gh_pr_view(r, n)
                result = await classify_one_pr(state)
                path = await deliver_to_inbox(result)
                print(f"  {r}#{n} → {result.bucket} ({result.reason}) → {path}")
            except Exception as e:
                print(f"  {r}#{n} → ERROR: {e}")
    asyncio.run(run())


@pr_state_app.command("scan")
def pr_state_classify_run(
    limit: int = typer.Option(50, help="max PRs to classify"),
) -> None:
    """Classify all open PRs; deposit results to classified.jsonl.

    Does NOT route — that happens in `sweep pr-state route` at takt time.
    Decoupling means routing rule changes don't require re-classification.
    """
    async def run() -> None:
        prs = await gh_search_open_authored(limit)
        print(f"# {len(prs)} open PRs → classified.jsonl")
        for raw in prs:
            r = raw["repository"]["nameWithOwner"]
            n = raw["number"]
            try:
                state = await gh_pr_view(r, n)
                result = await classify_one_pr(state)
                await deposit_classified(result)
                print(f"  {r}#{n} → {result.bucket} (deposited)")
            except Exception as e:
                print(f"  {r}#{n} → ERROR: {e}")
    asyncio.run(run())


@pr_state_app.command("route")
def pr_state_route() -> None:
    """Read classified.jsonl, route each PR to its actor inbox."""
    async def run() -> None:
        result = await route_classified()
        print_json(result)
    asyncio.run(run())


@pr_state_app.command("workflow")
def pr_state_workflow(
    limit: int = typer.Option(50),
) -> None:
    """Temporal: run PrStateWorkflow once."""
    async def run() -> None:
        client = await Client.connect(TEMPORAL_ADDR)
        result = await client.execute_workflow(
            PrStateWorkflow.run,
            limit,
            id=f"pr-state-{uuid.uuid4().hex[:8]}",
            task_queue=SWEEP_TASK_QUEUE,
        )
        print_json(result)
    asyncio.run(run())
