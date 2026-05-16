"""UsagePoller — fire `probe_claude_usage` every 30 minutes.

30min cadence gives ~10 samples per 5h subscription window — fine
resolution for an operator who's checking "how much is left." Andon
on parse failure: if Claude Code reformats the /usage output, halt
the poller so the operator notices the staleness within one cycle
rather than seeing a frozen number for days.

Mirrors ProspectPuller's shape but is much simpler (no demand
gating — usage info is always wanted while the pipeline is up).
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from sweep.activities.usage_probe import probe_claude_usage


POLL_MINUTES = 30


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
