"""`sweep qa …` — standalone activity invocations + Temporal QaActor controls."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
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


@qa_app.command("backfill")
def qa_backfill(
    repo: str = typer.Option(..., help="owner/repo"),
    pr: int = typer.Option(..., help="PR number"),
    branch: str = typer.Option(None, help="PR head branch. Looked up from gh if omitted."),
    worktree: str = typer.Option(
        None, help="Path to a local checkout that has the fix branch + "
                   "default branch reachable. Required for fork-branch PRs "
                   "since the substrate's upstream clone can't reach them."),
    sender: str = typer.Option("backfill", help="Sender tag recorded on the card"),
) -> None:
    """Kick a qa card directly. New entry into the production lane,
    bypassing investigate. Pairs with `sweep attest backfill` and
    `sweep compose backfill` for end-to-end manual triggering."""
    import asyncio
    from pathlib import Path
    from sweep import gh_io
    from sweep.activities.qa import kick_qa_card

    if branch is None:
        meta = gh_io.pr_view(repo, pr, fields="headRefName")
        branch = (meta or {}).get("headRefName") if isinstance(meta, dict) else None
        if not branch:
            raise typer.Exit(f"could not resolve branch for {repo}#{pr}")

    if worktree and not Path(worktree).is_dir():
        raise typer.Exit(f"worktree {worktree!r} does not exist")

    async def _kick() -> str | None:
        return await kick_qa_card(
            repo=repo, branch=branch, pr=pr, sender=sender,
            worktree=worktree,
        )

    wf_id = asyncio.run(_kick())
    if wf_id is None:
        print("deposited card on qa.jsonl but signal failed "
              "(actor unwired or temporal down). The card persists "
              "and will be drained on next worker start.")
    else:
        print(f"kicked qa for {repo}#{pr} on {branch}")
        if worktree:
            print(f"  using local worktree: {worktree}")
        print(f"  watch: tail -f ~/.sweep/events.jsonl | grep {repo}")


@qa_app.command("backfill-bulk")
def qa_backfill_bulk(
    limit: int = typer.Option(50, help="Cap on PRs to enqueue"),
    only_with_tests: bool = typer.Option(
        True, "--only-with-tests/--all",
        help="Only enqueue PRs whose diff contains test files "
             "(per the same _looks_like_test heuristic attest uses). "
             "Strong predictor of attestable outcome."),
    dry: bool = typer.Option(False, "--dry", help="Print plan, don't kick"),
    skip_evicted: bool = typer.Option(
        True, "--skip-evicted/--include-evicted",
        help="Honor ~/.sweep/control/sift_evicted.txt"),
) -> None:
    """Bulk-enqueue open authored PRs to the qa inbox. Reads `gh
    search prs --author <you> --state open`, filters via heuristics,
    kicks each as a separate qa card. The substrate processes them
    serially (with backpressure at qa→attest); failures route via the
    new no_tests_in_pr / test_passes_on_master / test_fails_on_fix
    verdicts; sinks accumulate for `sweep evict process-sink`.
    """
    import asyncio
    import fnmatch
    from pathlib import Path
    from sweep import gh_io
    from sweep.activities.qa import kick_qa_card
    from sweep.activities.qa import _looks_like_test

    # Load eviction list (fnmatch patterns; comments / blanks skipped).
    evicted_patterns: list[str] = []
    if skip_evicted:
        for txt in (
            Path.home() / ".sweep" / "control" / "sift_evicted.txt",
            Path.home() / ".sweep" / "control" / "sift_kill_list.txt",
        ):
            if not txt.exists():
                continue
            for line in txt.read_text().splitlines():
                s = line.split("#", 1)[0].strip()
                if s:
                    evicted_patterns.append(s)

    def _is_evicted(repo: str) -> bool:
        return any(fnmatch.fnmatch(repo, p) for p in evicted_patterns)

    # Load sink as the canonical "we're done with this" set. Skipping
    # sunk (repo, pr) pairs catches every disposition we've made —
    # approved-by-member, drafted+evicted, no_tests_in_pr — without
    # us having to enumerate the reasons here. Local-only check.
    sink_path = Path.home() / ".sweep" / "inbox" / "sink.jsonl"
    sunk_pairs: set[tuple[str, int]] = set()
    if sink_path.exists():
        for line in sink_path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                r, p = row.get("repo"), row.get("pr")
                if r and p:
                    sunk_pairs.add((r, int(p)))
            except Exception:
                continue

    user = (gh_io.api("user", ttl=86400) or {}).get("login") or ""
    if not user:
        raise typer.Exit("could not resolve gh user")
    prs = gh_io.search_prs(
        f"author:{user}", state="open", limit=min(limit * 2, 100),
        fields="repository,number,title,url,createdAt,updatedAt",
        ttl=60,
    )
    if not isinstance(prs, list):
        raise typer.Exit("gh search prs returned non-list")

    plan: list[tuple[str, int, str]] = []
    auto_sunk: list[tuple[str, int, str]] = []
    for p in prs:
        repo = (p.get("repository") or {}).get("nameWithOwner") or ""
        num = p.get("number")
        if not repo or not num:
            continue
        if _is_evicted(repo):
            continue
        if (repo, int(num)) in sunk_pairs:
            continue
        # Per-PR shape filter via gh pr view (cached).
        try:
            view = gh_io.pr_view(repo, int(num),
                                  fields="isDraft,reviewDecision,headRefName",
                                  ttl=300)
        except Exception:
            continue
        if view.get("isDraft"):
            continue
        # APPROVED → sink (maintainer's court, out of our rotation).
        # Auto-sinking here avoids the wasted attest cycle AND makes
        # the sink the single source of truth for "PRs we're done
        # with." Same shape that remit's classifier uses for the
        # APPROVED + MERGEABLE + green path.
        if view.get("reviewDecision") == "APPROVED":
            auto_sunk.append((repo, int(num), "approved — maintainers court"))
            continue
        branch = view.get("headRefName") or ""
        if not branch:
            continue
        if only_with_tests:
            # Cheap diff name-only check.
            try:
                r = subprocess.run(
                    ["gh", "pr", "diff", str(num), "--repo", repo,
                     "--name-only"],
                    capture_output=True, text=True, timeout=15,
                )
                if r.returncode != 0:
                    continue
                files = [f for f in (r.stdout or "").splitlines() if f]
                if not any(_looks_like_test(f) for f in files):
                    continue
            except Exception:
                continue
        plan.append((repo, int(num), branch))
        if len(plan) >= limit:
            break

    print(f"plan: {len(plan)} PRs to enqueue"
          f"{' (only-with-tests)' if only_with_tests else ''}")
    for repo, num, br in plan:
        print(f"  {repo}#{num}  {br}")
    if auto_sunk:
        print(f"\nauto-sink: {len(auto_sunk)} approved PRs → sink.jsonl")
        for repo, num, reason in auto_sunk:
            print(f"  {repo}#{num}  ({reason})")
    if dry:
        return

    # Persist auto-sink rows before kicking. Even if the qa kicks
    # fail, the sink reflects the operator's decision.
    if auto_sunk:
        import datetime as _dt
        sink = Path.home() / ".sweep" / "inbox" / "sink.jsonl"
        sink.parent.mkdir(parents=True, exist_ok=True)
        ts = _dt.datetime.now(_dt.timezone.utc).isoformat()
        with open(sink, "a") as f:
            for repo, num, reason in auto_sunk:
                f.write(json.dumps({
                    "ts": ts, "repo": repo, "pr": num,
                    "reason": reason, "state": "OPEN_APPROVED",
                }) + "\n")

    async def _kick_all():
        for repo, num, br in plan:
            wf = await kick_qa_card(
                repo=repo, branch=br, pr=num,
                sender="bulk-backfill",
            )
            print(f"  kicked qa for {repo}#{num} on {br}  wf={wf}")

    asyncio.run(_kick_all())
    print(f"\nenqueued {len(plan)} card(s) into qa.jsonl, "
          f"sunk {len(auto_sunk)} approved")


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
