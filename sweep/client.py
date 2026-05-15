"""Sweep client. Subcommand-structured by actor, Typer-driven.

  sweep qa test    --repo R --branch B --worktree W --test-cmd 'pytest'
  sweep qa codex   --repo R --branch B --worktree W
  sweep qa gemini  --repo R --branch B --worktree W --round 1
  sweep qa full    --repo R --branch B --worktree W --test-cmd 'pytest'
  sweep qa actor signal | status | clear      # Temporal QaActor controls

  sweep pr-state classify --repo R --pr N
  sweep pr-state run      --limit 30
  sweep pr-state workflow --limit 30          # Temporal one-shot

  sweep inbox qa | drip | investigate | retro

Activities are directly importable for in-process use; this CLI is the
shell entry. Temporal commands need the worker + dev server up.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import subprocess
import uuid
from dataclasses import asdict
from pathlib import Path

import typer
from temporalio.client import Client

from sweep import models
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
TEMPORAL_ADDR = "localhost:7233"


def _new_msg_id() -> str:
    return f"dev-{uuid.uuid4().hex[:8]}"


def _build_req(repo: str, branch: str, worktree: str, test_cmd: str, msg_id: str | None) -> QaOneEntryRequest:
    return QaOneEntryRequest(
        msg_id=msg_id or _new_msg_id(),
        repo=repo,
        branch=branch,
        worktree=worktree,
        test_cmd=test_cmd,
        issue=None,
    )


def _diff(worktree: str) -> str:
    return subprocess.run(
        ["git", "-C", worktree, "diff", "origin/HEAD..."],
        capture_output=True, text=True,
    ).stdout


def _print_json(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


# ============================================================ qa


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
    req = _build_req(repo, branch, worktree, test_cmd, msg_id)
    _print_json(asdict(asyncio.run(test_attestation(req))))


@qa_app.command("codex")
def qa_codex(
    repo: str = typer.Option(..., help="owner/repo"),
    branch: str = typer.Option("", help="fix branch"),
    worktree: str = typer.Option(".", help="local clone path"),
    msg_id: str | None = typer.Option(None),
) -> None:
    """Run codex_review only."""
    req = _build_req(repo, branch, worktree, "", msg_id)
    _print_json(asdict(asyncio.run(codex_review(req, _diff(worktree)))))


@qa_app.command("gemini")
def qa_gemini(
    repo: str = typer.Option(..., help="owner/repo"),
    branch: str = typer.Option("", help="fix branch"),
    worktree: str = typer.Option(".", help="local clone path"),
    round: int = typer.Option(1, "--round", "-r"),
    msg_id: str | None = typer.Option(None),
) -> None:
    """Run gemini_review one round."""
    req = _build_req(repo, branch, worktree, "", msg_id)
    _print_json(asdict(asyncio.run(gemini_review(req, _diff(worktree), round))))


@qa_app.command("full")
def qa_full(
    repo: str = typer.Option(..., help="owner/repo"),
    branch: str = typer.Option("", help="fix branch"),
    worktree: str = typer.Option(".", help="local clone path"),
    test_cmd: str = typer.Option("", help="test command"),
    msg_id: str | None = typer.Option(None),
) -> None:
    """Run qa_one_entry end-to-end (composer, no Temporal)."""
    req = _build_req(repo, branch, worktree, test_cmd, msg_id)
    _print_json(asdict(asyncio.run(qa_one_entry(req))))


# ----- qa actor (Temporal)

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


# ============================================================ pr-state


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
        _print_json(asdict(result))
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
        _print_json(result)
    asyncio.run(run())


# ============================================================ inbox


def _inspect_inbox(actor: str) -> None:
    inbox = Path.home() / ".sweep" / "inbox" / f"{actor}.jsonl"
    if not inbox.exists():
        print(f"# {inbox} — no messages")
        return
    seen: dict[str, dict] = {}
    raw = 0
    for line in inbox.read_text().splitlines():
        if not line.strip():
            continue
        raw += 1
        try:
            m = json.loads(line)
        except json.JSONDecodeError:
            continue
        if m.get("msg_id"):
            seen[m["msg_id"]] = m

    acks_path = Path.home() / ".sweep" / "inbox" / "_acks.jsonl"
    acked: set[str] = set()
    if acks_path.exists():
        for line in acks_path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                a = json.loads(line)
                if a.get("msg_id"):
                    acked.add(a["msg_id"])
            except json.JSONDecodeError:
                pass

    unacked = [m for mid, m in seen.items() if mid not in acked]
    print(f"# {inbox}")
    print(
        f"# raw_lines={raw}  unique_msgs={len(seen)}  "
        f"unacked={len(unacked)}  acked={len(acked)}"
    )
    print()
    for m in sorted(unacked, key=lambda x: x.get("ts", "")):
        intent = m.get("intent", "?")
        repo = m.get("repo", "?")
        pr = m.get("pr") or "-"
        ts = m.get("ts", "")[:19]
        reason = (m.get("payload") or {}).get("reason", "")
        print(f"  [{ts}] {intent:9s} {repo}#{pr}  {reason}")


inbox_app = typer.Typer(help="Inspect one actor inbox", no_args_is_help=True, invoke_without_command=True)


@inbox_app.callback(invoke_without_command=True)
def inbox_default(
    ctx: typer.Context,
    actor: str = typer.Argument(None, help="qa | drip | investigate | retro"),
) -> None:
    """Read ~/.sweep/inbox/<actor>.jsonl, dedupe by msg_id."""
    if actor is None:
        print(ctx.get_help())
        raise typer.Exit(0)
    if actor not in {"qa", "drip", "investigate", "retro"}:
        raise typer.BadParameter(
            f"unknown actor {actor!r}; pick qa|drip|investigate|retro"
        )
    _inspect_inbox(actor)


# ============================================================ root


app = typer.Typer(
    help="Sweep — Temporal-supervised PR pipeline",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
app.add_typer(qa_app, name="qa")
app.add_typer(pr_state_app, name="pr-state")
app.add_typer(inbox_app, name="inbox")


@app.command("models")
def models_cmd() -> None:
    """Show model registry, role defaults, adversary cascade."""
    print(models.describe())


# ----- punch list: cross-inbox actionable view


def _read_inbox(actor: str) -> tuple[list[dict], set[str]]:
    """Return (unacked messages, all_acked_msg_ids)."""
    inbox = Path.home() / ".sweep" / "inbox" / f"{actor}.jsonl"
    if not inbox.exists():
        return [], set()
    seen: dict[str, dict] = {}
    for line in inbox.read_text().splitlines():
        if not line.strip():
            continue
        try:
            m = json.loads(line)
            if m.get("msg_id"):
                seen[m["msg_id"]] = m
        except json.JSONDecodeError:
            pass

    acks_path = Path.home() / ".sweep" / "inbox" / "_acks.jsonl"
    acked: set[str] = set()
    if acks_path.exists():
        for line in acks_path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                a = json.loads(line)
                if a.get("msg_id"):
                    acked.add(a["msg_id"])
            except json.JSONDecodeError:
                pass
    return [m for mid, m in seen.items() if mid not in acked], acked


SPARK_CHARS = " ▁▂▃▄▅▆▇█"  # 9 levels including empty


def _sparkline(counts: list[int]) -> str:
    """Render counts as a Unicode block sparkline."""
    if not counts:
        return ""
    peak = max(counts) or 1
    return "".join(SPARK_CHARS[min(8, int(round(c * 8 / peak)))] for c in counts)


def _bucketize(timestamps: list[str], bucket_minutes: int, n_buckets: int) -> list[int]:
    """Bucket ISO 8601 timestamps into the most-recent n_buckets windows of bucket_minutes."""
    if not timestamps:
        return [0] * n_buckets
    now = dt.datetime.now(dt.timezone.utc)
    edges = [now - dt.timedelta(minutes=bucket_minutes * (n_buckets - i)) for i in range(n_buckets + 1)]
    counts = [0] * n_buckets
    for ts in timestamps:
        try:
            t = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        for i in range(n_buckets):
            if edges[i] <= t < edges[i + 1]:
                counts[i] += 1
                break
    return counts


def _oldest_age_str(msgs: list[dict]) -> str:
    if not msgs:
        return "—"
    now = dt.datetime.now(dt.timezone.utc)
    oldest = None
    for m in msgs:
        ts = m.get("ts", "")
        try:
            t = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if oldest is None or t < oldest:
                oldest = t
        except (ValueError, AttributeError):
            continue
    if oldest is None:
        return "—"
    delta = now - oldest
    secs = int(delta.total_seconds())
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        return f"{secs // 3600}h"
    return f"{secs // 86400}d"


@app.command("punch")
def punch(
    include_wait: bool = typer.Option(False, "--include-wait", help="Also show retro/wait audits"),
    spark_minutes: int = typer.Option(10, help="Sparkline bucket size in minutes"),
    spark_buckets: int = typer.Option(12, help="Number of sparkline buckets (default 12 × 10min = 2h)"),
    rich_mode: bool = typer.Option(False, "--rich", help="Render Rich panels instead of markdown"),
) -> None:
    """Factory-floor kanban view + per-station punch list.

    Default output is GitHub-flavored markdown — renders in Claude Code, looks
    fine in a plain terminal, and pipes cleanly to files / clipboard. Use
    --rich for Rich panels in a live terminal.
    """
    ACTIONABLE = ["drip", "investigate", "qa"]
    if include_wait:
        ACTIONABLE = ACTIONABLE + ["retro"]

    BOUND = {"qa": 3, "drip": 5, "investigate": 5, "retro": None}
    ACTION_HINT = {
        "qa":          "re-attest (CI failed / gates stale)",
        "drip":        "advance status (close / rebase / ship)",
        "investigate": "respond to maintainer",
        "retro":       "audit only (wait bucket)",
    }

    sections: dict[str, list[dict]] = {}
    for actor in ACTIONABLE:
        msgs, _ = _read_inbox(actor)
        sections[actor] = sorted(msgs, key=lambda x: x.get("ts", ""))

    def _status_for(actor: str, wip: int, bound: int | None) -> str:
        if wip == 0:
            return "idle"
        if bound is not None and wip > bound:
            return "**ANDON**"
        if actor == "retro":
            return "history"
        return "working"

    rows: list[tuple[str, int, str, str, str, str]] = []
    for actor in ACTIONABLE:
        msgs = sections[actor]
        wip = len(msgs)
        bound = BOUND.get(actor)
        sparks = _bucketize([m.get("ts", "") for m in msgs], spark_minutes, spark_buckets)
        spark = _sparkline(sparks) or "·" * spark_buckets
        bound_str = "∞" if bound is None else str(bound)
        rows.append((
            actor,
            wip,
            bound_str,
            _oldest_age_str(msgs),
            spark,
            _status_for(actor, wip, bound),
        ))

    if rich_mode:
        _punch_rich(rows, sections, ACTIONABLE, ACTION_HINT, include_wait, spark_buckets)
        return

    # --- markdown output ----------------------------------------------------
    print("# coding factory — kanban")
    print()
    print("`intake: pr-state` (reads GitHub, classifies, routes by bucket) →")
    print()
    print(f"| station | WIP / bound | oldest | flow ({spark_minutes}m × {spark_buckets}) | status |")
    print( "|---|---:|---|---|---|")
    for actor, wip, bound_str, oldest, spark, status in rows:
        print(f"| → {actor} | {wip} / {bound_str} | {oldest} | `{spark}` | {status} |")
    print()

    total = sum(len(sections[a]) for a in ACTIONABLE if a != "retro")
    if total == 0 and not include_wait:
        print("_nothing actionable — pipeline idle_")
        return

    for actor in ACTIONABLE:
        msgs = sections[actor]
        if not msgs:
            continue
        if actor == "retro" and not include_wait:
            continue
        print(f"## {actor} ({len(msgs)}) — {ACTION_HINT[actor]}")
        print()
        for m in msgs:
            repo = m.get("repo", "?")
            pr = m.get("pr") or "-"
            payload = m.get("payload") or {}
            reason = payload.get("reason", "")
            ts = m.get("ts", "")[:19]
            print(f"- **{repo}#{pr}** — {reason}  _({ts})_")
        print()


def _punch_rich(rows, sections, actionable, action_hint, include_wait, spark_buckets):
    """Rich-rendered fallback (--rich)."""
    from rich.columns import Columns
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text

    console = Console()

    source = Panel(
        Text("pr-state\n(dispatcher)\n\nreads GitHub\nroutes by bucket", justify="center"),
        title="intake",
        border_style="dim",
        width=18,
        padding=(0, 1),
    )
    panels = []
    for actor, wip, bound_str, oldest, spark, status in rows:
        if status.startswith("**ANDON"):
            border, color, label = "red", "red bold", "ANDON"
        elif status == "idle":
            border, color, label = "green", "green", "idle"
        elif status == "history":
            border, color, label = "dim", "dim", "history"
        else:
            border, color, label = "yellow", "yellow", "working"
        body = Text()
        body.append("WIP   ", style="dim"); body.append(f"{wip}", style="bold"); body.append(f" / {bound_str}\n", style="dim")
        body.append(f"old   {oldest}\n", style="dim")
        body.append("flow  ", style="dim"); body.append(spark, style="cyan"); body.append("\n")
        body.append(label, style=color)
        panels.append(Panel(body, title=f"[bold]{actor}[/]", border_style=border, width=22, padding=(0, 1)))

    console.print()
    console.print(Text("                       coding factory — kanban", style="bold dim"))
    console.print()
    console.print(Columns([source] + panels, equal=False, padding=(0, 1)))
    console.print()

    for actor in actionable:
        msgs = sections[actor]
        if not msgs:
            continue
        if actor == "retro" and not include_wait:
            continue
        console.print(f"[bold]{actor}[/] ({len(msgs)}) — [dim]{action_hint[actor]}[/]")
        for m in msgs:
            intent = m.get("intent", "?")
            repo = m.get("repo", "?")
            pr = m.get("pr") or "-"
            payload = m.get("payload") or {}
            reason = payload.get("reason", "")
            console.print(f"  [bold cyan]{repo}#{pr}[/]  [{intent}]  {reason}")
        console.print()


if __name__ == "__main__":
    app()
