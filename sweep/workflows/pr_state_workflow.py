"""PrStateWorkflow — runs pr-state across all my open PRs and delivers a
message per PR to the matching inbox.

Designed to be invoked as a fresh execution per tick (e.g. cron-scheduled
every 5 min). Not a long-running actor — each run is one classification
pass.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from sweep.activities.pr_state import (
        classify_one_pr,
        deliver_to_inbox,
        gh_pr_view,
        gh_search_open_authored,
    )


@workflow.defn
class PrStateWorkflow:
    @workflow.run
    async def run(self, limit: int = 50) -> dict:
        prs = await workflow.execute_activity(
            gh_search_open_authored,
            limit,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        counts: dict[str, int] = {}
        delivered: list[str] = []

        for raw in prs:
            repo = raw["repository"]["nameWithOwner"]
            pr = raw["number"]
            try:
                state = await workflow.execute_activity(
                    gh_pr_view,
                    args=[repo, pr],
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )
                result = await workflow.execute_activity(
                    classify_one_pr,
                    state,
                    start_to_close_timeout=timedelta(seconds=10),
                )
                path = await workflow.execute_activity(
                    deliver_to_inbox,
                    result,
                    start_to_close_timeout=timedelta(seconds=5),
                )
                counts[result.bucket] = counts.get(result.bucket, 0) + 1
                delivered.append(f"{repo}#{pr} → {result.bucket}")
            except Exception as e:
                workflow.logger.error("pr-state failed for %s#%s: %s", repo, pr, e)

        # Search attribute lets the UI / queries filter pr-state runs.
        return {"counts": counts, "delivered": delivered}
