"""NotificationPoller — push-shaped replacement for periodic full PR scans.

Polls GitHub's notifications endpoint every POLL_INTERVAL_S. For each
unread PR thread, reuses the existing pr-state activities
(`gh_pr_view` → `classify_one_pr` → `deliver_to_inbox`) and then
acks via `mark_thread_read`. Marking-read is the watermark; if a tick
fails partway through, the unprocessed threads stay unread and the
next poll re-fetches them.

Tradeoff vs. PrStateWorkflow's full-scan: this only touches PRs whose
state actually changed (review_requested, mention, state_change, etc.),
so it's ~20x cheaper than rescanning all open authored PRs on a cadence.
PrStateWorkflow stays as a manual escape hatch (`sweep pr-state run`).
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from sweep.activities.notifications import (
        POLL_INTERVAL_S,
        mark_thread_read,
        poll_github_notifications,
    )
    from sweep.activities.pause_gate import should_idle
    from sweep.activities.remit import kick_remit_card


@workflow.defn
class NotificationPoller:
    def __init__(self) -> None:
        self.last_poll_iso: str = ""
        self.polls_total: int = 0
        self.threads_processed: int = 0
        self.last_threads_count: int = 0
        self.last_state: str = "init"

    @workflow.query
    def state(self) -> dict:
        return {
            "last_poll_iso": self.last_poll_iso,
            "polls_total": self.polls_total,
            "threads_processed": self.threads_processed,
            "last_threads_count": self.last_threads_count,
            "last_state": self.last_state,
        }

    @workflow.run
    async def run(self) -> None:
        while True:
            # Inbox-boundary pause check: idle while paused. Don't even
            # poll GitHub when the line is down — burning notifications
            # API quota under pause is the same waste as any other.
            while await workflow.execute_activity(
                should_idle, args=["notifications"],
                start_to_close_timeout=timedelta(seconds=5),
                retry_policy=RetryPolicy(maximum_attempts=2),
            ):
                await workflow.sleep(timedelta(seconds=10))
            self.last_poll_iso = workflow.now().isoformat()
            self.polls_total += 1
            try:
                result = await workflow.execute_activity(
                    poll_github_notifications,
                    start_to_close_timeout=timedelta(seconds=45),
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )
            except Exception as e:
                workflow.logger.warning("notifications poll failed: %s", e)
                self.last_state = "poll_failed"
                await workflow.sleep(timedelta(seconds=POLL_INTERVAL_S))
                continue

            threads = result.get("threads", [])
            self.last_threads_count = len(threads)
            interval = int(result.get("poll_interval_s", POLL_INTERVAL_S))

            for t in threads:
                repo, pr = t.get("repo", ""), t.get("pr", 0)
                thread_id = t.get("thread_id", "")
                if not (repo and pr and thread_id):
                    continue
                try:
                    # Emit a raw card to remit-actor's inbox. Remit owns
                    # the classify-and-route policy now; the poller is a
                    # dumb emitter (its only job: turn GitHub
                    # notifications into local cards). This keeps the
                    # post-ship engagement loop first-class instead of
                    # buried inside the poller's tick.
                    await workflow.execute_activity(
                        kick_remit_card,
                        args=[repo, pr],
                        start_to_close_timeout=timedelta(seconds=5),
                        retry_policy=RetryPolicy(maximum_attempts=2),
                    )
                except Exception as e:
                    # Don't ack — thread stays unread, next poll retries.
                    workflow.logger.error(
                        "notification process failed for %s#%s: %s",
                        repo, pr, e,
                    )
                    continue

                # Ack only after delivery. If mark-read fails, we'll
                # re-process this thread next tick — harmless given
                # the actor inbox dedupes on msg_id.
                try:
                    await workflow.execute_activity(
                        mark_thread_read,
                        thread_id,
                        start_to_close_timeout=timedelta(seconds=15),
                        retry_policy=RetryPolicy(maximum_attempts=2),
                    )
                    self.threads_processed += 1
                except Exception as e:
                    workflow.logger.warning(
                        "mark_thread_read failed for %s: %s", thread_id, e,
                    )

            self.last_state = "ok"
            await workflow.sleep(timedelta(seconds=interval))
