"""`sweep investigate enqueue` — append one issue to the investigate inbox.

Called by /triage when its decision is `investigate`. Writes a
Message to ~/.sweep/inbox/investigate.jsonl AND signals
InvestigateActor (SkillActor instance with investigate_cycle).

The investigate inbox is the seam between the "decide" station
(triage) and the "investigate" station (HG run via /investigate).
Per-issue end-to-end; no batching.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json

import typer

from sweep.inbox_state import INBOX_DIR
from sweep.types import Message


investigate_app = typer.Typer(
    help="Investigate inbox — feeds /investigate via InvestigateActor.",
    no_args_is_help=True,
)


@investigate_app.command("enqueue")
def investigate_enqueue(
    repo: str = typer.Option(..., "--repo", help="owner/repo"),
    issue: int = typer.Option(..., "--issue", help="issue number"),
    reason: str = typer.Option("triage:investigate", "--reason",
                                help="One-sentence rationale from /triage"),
) -> None:
    """Append one Message to investigate.jsonl and signal InvestigateActor."""
    ts = dt.datetime.now(dt.timezone.utc)
    ts_minute = ts.strftime("%Y-%m-%dT%H:%MZ")
    slug = repo.replace("/", "-")
    msg = Message(
        msg_id=f"triage-{ts_minute}-{slug}-{issue}",
        sender="triage",
        intent="investigate",
        repo=repo,
        pr=issue,
        branch=None,
        payload={"reason": reason, "kind": "issue"},
        ts=ts.isoformat(),
    )
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    path = INBOX_DIR / "investigate.jsonl"
    from dataclasses import asdict
    with path.open("a") as f:
        f.write(json.dumps(asdict(msg)) + "\n")

    # Signal the actor — same shape as prospect → triage signal.
    async def _signal() -> None:
        try:
            from temporalio.client import Client
            from sweep.cli._common import SWEEP_TASK_QUEUE, INVESTIGATE_ACTOR_ID
            from sweep.system import TEMPORAL_ADDR
            from sweep.workflows.skill_actor import SkillActor

            c = await Client.connect(TEMPORAL_ADDR)
            handle = c.get_workflow_handle(INVESTIGATE_ACTOR_ID)
            await handle.signal(SkillActor.deliver, msg)
        except Exception:
            pass  # best effort; the file write is the durable record
    asyncio.run(_signal())
    typer.echo(f"enqueued: {repo}#{issue}")


def register(app: typer.Typer) -> None:
    app.add_typer(investigate_app, name="investigate")
