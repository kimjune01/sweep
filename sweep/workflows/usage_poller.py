"""UsagePoller — fire `probe_claude_usage` every 5 minutes.

5min cadence gives ~60 samples per 5h subscription window. We over-
sample on purpose: the /usage panel is flaky (sometimes returns
nothing), and a single failed read shouldn't leave the wasteboard
stale for 30 minutes. The probe writes its last good answer to disk;
flaky reads are logged and ignored — the cache survives.

Mirrors the older actor-puller shape but is much simpler (no demand
gating — usage info is always wanted while the pipeline is up).
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from sweep.activities.usage_probe import probe_claude_usage


POLL_MINUTES = 5


@workflow.defn
class UsagePoller:
    def __init__(self) -> None:
        self.last_probe_iso: str = ""
        self.probes_total: int = 0
        self.halted: bool = False
        self.last_error: str = ""

    @workflow.signal
    async def clear_andon(self) -> None:
        self.halted = False
        self.last_error = ""

    @workflow.query
    def state(self) -> dict:
        return {
            "last_probe_iso": self.last_probe_iso,
            "probes_total": self.probes_total,
            "halted": self.halted,
            "last_error": self.last_error,
            "poll_minutes": POLL_MINUTES,
        }

    @workflow.run
    async def run(self) -> None:
        while True:
            await workflow.wait_condition(lambda: not self.halted)
            try:
                await workflow.execute_activity(
                    probe_claude_usage,
                    start_to_close_timeout=timedelta(minutes=2),
                    retry_policy=RetryPolicy(
                        maximum_attempts=2,
                        non_retryable_error_types=["ApplicationError"],
                    ),
                )
                self.last_probe_iso = workflow.now().isoformat()
                self.probes_total += 1
            except Exception as e:
                # Andon on probe failure — usually parse-failure from a
                # Claude Code version bump reformatting /usage. Halt;
                # operator clears via `sweep usage actor clear` (or
                # equivalent signal) once the parser is updated.
                self.halted = True
                self.last_error = str(e)[:300]
                workflow.logger.error(
                    "usage probe andon: %s", self.last_error
                )
            await workflow.sleep(timedelta(minutes=POLL_MINUTES))
