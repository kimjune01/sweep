"""`sweep pr-state …` — classify, deliver, or run the Temporal workflow."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import asdict

import typer
from temporalio.client import Client

from sweep.activities.pr_state import (
    classify_one_pr,
    deliver_to_inbox,
    gh_pr_view,
    gh_search_open_authored,
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
