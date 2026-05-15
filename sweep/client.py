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


def _load_msg_id_set(path: Path) -> set[str]:
    out: set[str] = set()
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            a = json.loads(line)
            if a.get("msg_id"):
                out.add(a["msg_id"])
        except json.JSONDecodeError:
            pass
    return out


def _read_inbox(actor: str) -> tuple[list[dict], set[str]]:
    """Backward-compat: return (unacked messages, acked_msg_ids)."""
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

    acked = _load_msg_id_set(Path.home() / ".sweep" / "inbox" / "_acks.jsonl")
    return [m for mid, m in seen.items() if mid not in acked], acked


def _inbox_states(actor: str) -> dict[str, list[dict]]:
    """Partition an inbox into {'queued', 'in_flight', 'done'}.

    queued    = msg present, no start record
    in_flight = msg present, start record but no ack
    done      = msg present, ack record (regardless of start)
    """
    inbox = Path.home() / ".sweep" / "inbox" / f"{actor}.jsonl"
    seen: dict[str, dict] = {}
    if inbox.exists():
        for line in inbox.read_text().splitlines():
            if not line.strip():
                continue
            try:
                m = json.loads(line)
                if m.get("msg_id"):
                    seen[m["msg_id"]] = m
            except json.JSONDecodeError:
                pass

    started = _load_msg_id_set(Path.home() / ".sweep" / "inbox" / "_started.jsonl")
    acked = _load_msg_id_set(Path.home() / ".sweep" / "inbox" / "_acks.jsonl")

    states: dict[str, list[dict]] = {"queued": [], "in_flight": [], "done": []}
    for mid, m in seen.items():
        if mid in acked:
            states["done"].append(m)
        elif mid in started:
            states["in_flight"].append(m)
        else:
            states["queued"].append(m)
    return states


SPARK_CHARS = " ▁▂▃▄▅▆▇█"  # 9 levels including empty
DITHER_CHARS = " ░▒▓█"  # 5 shades — used for daily event density


def _sparkline(counts: list[int]) -> str:
    """Render counts as a Unicode block sparkline. Peak-relative."""
    if not counts:
        return ""
    peak = max(counts) or 1
    return "".join(SPARK_CHARS[min(8, int(round(c * 8 / peak)))] for c in counts)


def _sparkline_pct(counts: list[int], cap: int | None) -> str:
    """Render counts as % of cap (full block = at cap, clamped to 1.0).

    When cap is None or 0, falls back to peak-relative (_sparkline).
    """
    if not counts:
        return ""
    if not cap:
        return _sparkline(counts)
    return "".join(
        SPARK_CHARS[min(8, int(round(min(c / cap, 1.0) * 8)))] for c in counts
    )


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


def _rate_per_hour(counts: list[int], bucket_minutes: int) -> float:
    """Total events / window hours."""
    total = sum(counts)
    hours = (len(counts) * bucket_minutes) / 60.0
    return total / hours if hours else 0.0


def _dither(counts: list[int]) -> str:
    """Map counts to a 5-shade dither (' ░▒▓█'). 0→space, 1→░, more → denser."""
    if not counts:
        return ""
    out = []
    for c in counts:
        if c <= 0:
            out.append(DITHER_CHARS[0])
        elif c <= 2:
            out.append(DITHER_CHARS[1])
        elif c <= 4:
            out.append(DITHER_CHARS[2])
        elif c <= 7:
            out.append(DITHER_CHARS[3])
        else:
            out.append(DITHER_CHARS[4])
    return "".join(out)


def _outcomes(days: int = 7) -> dict:
    """Fetch merged + closed-but-not-merged counts per day via gh.

    Lightly cached at ~/.sweep/cache/outcomes.json (1h TTL) so `punch`
    is fast on repeated runs.
    """
    import time as _time
    cache = Path.home() / ".sweep" / "cache" / "outcomes.json"
    if cache.exists():
        try:
            data = json.loads(cache.read_text())
            if data.get("days") == days and (_time.time() - data.get("fetched_at", 0)) < 3600:
                return data
        except (json.JSONDecodeError, OSError):
            pass

    end = dt.datetime.now(dt.timezone.utc).date()
    start = end - dt.timedelta(days=days - 1)

    user = subprocess.run(
        ["gh", "api", "user", "--jq", ".login"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    if not user:
        return {"days": days, "merged": 0, "closed": 0,
                "merged_per_day": [0] * days, "closed_per_day": [0] * days,
                "fetched_at": _time.time(), "user": ""}

    def _query(date_field: str, extra_filters: list[str]) -> list[dict]:
        out = subprocess.run(
            [
                "gh", "search", "prs",
                "--author", user,
                f"--{date_field}", f">={start.isoformat()}",
                *extra_filters,
                "--limit", "200",
                "--json", "repository,number,updatedAt,closedAt,state",
            ],
            capture_output=True, text=True, check=False,
        )
        try:
            return json.loads(out.stdout or "[]")
        except json.JSONDecodeError:
            return []

    merged_prs = _query("merged-at", [])
    # Closed-but-not-merged: state=closed AND closed-at in range.
    closed_prs = [
        pr for pr in _query("closed", ["--state", "closed"])
        if pr.get("state") != "MERGED"
    ]

    def _bucket_by_day(prs: list[dict], date_key: str) -> list[int]:
        counts = [0] * days
        for pr in prs:
            ts = pr.get(date_key) or pr.get("updatedAt") or ""
            try:
                t = dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).date()
            except (ValueError, AttributeError):
                continue
            idx = (t - start).days
            if 0 <= idx < days:
                counts[idx] += 1
        return counts

    merged_per_day = _bucket_by_day(merged_prs, "updatedAt")
    closed_per_day = _bucket_by_day(closed_prs, "closedAt")

    result = {
        "days": days,
        "user": user,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "merged": sum(merged_per_day),
        "closed": sum(closed_per_day),
        "merged_per_day": merged_per_day,
        "closed_per_day": closed_per_day,
        "fetched_at": _time.time(),
    }
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(result))
    return result


def _stddev(counts: list[int]) -> float:
    """Sample stddev of bucket counts. Variance gauge — steady=low, spiky=high."""
    if len(counts) < 2:
        return 0.0
    mean = sum(counts) / len(counts)
    return (sum((c - mean) ** 2 for c in counts) / (len(counts) - 1)) ** 0.5


def _variance_glyph(counts: list[int]) -> str:
    """Three-position dash for variance: _ low, — mid, ‾ high (spiky)."""
    if not counts or sum(counts) == 0:
        return " "
    mean = sum(counts) / len(counts)
    if mean == 0:
        return "_"
    sigma = _stddev(counts)
    cv = sigma / mean  # coefficient of variation — scale-free
    if cv < 0.5:
        return "_"
    if cv < 1.5:
        return "—"
    return "‾"


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
    outcome_days: int = typer.Option(7, help="Outcomes window in days"),
    rich_mode: bool = typer.Option(False, "--rich", help="Render Rich panels instead of markdown"),
    no_outcomes: bool = typer.Option(False, "--no-outcomes", help="Skip the gh-backed outcomes fetch"),
    watch: bool = typer.Option(False, "--watch", "-w", help="Refresh continuously as a live dashboard"),
    interval: int = typer.Option(30, "--interval", "-i", help="Refresh interval (seconds) when --watch"),
) -> None:
    """Factory-floor kanban view + per-station punch list.

    Default output is GitHub-flavored markdown — renders in Claude Code, looks
    fine in a plain terminal, and pipes cleanly to files / clipboard. Use
    --rich for Rich panels in a live terminal. --watch refreshes in place
    every --interval seconds.
    """
    if watch:
        import time as _time
        try:
            while True:
                # Clear screen + cursor home (ANSI). Works in most terminals.
                print("\x1b[2J\x1b[H", end="")
                _punch_once(include_wait, spark_minutes, spark_buckets, outcome_days,
                            rich_mode, no_outcomes)
                print()
                print(f"_refreshes every {interval}s — Ctrl-C to exit_")
                _time.sleep(interval)
        except KeyboardInterrupt:
            return
        return
    _punch_once(include_wait, spark_minutes, spark_buckets, outcome_days,
                rich_mode, no_outcomes)


def _punch_once(include_wait, spark_minutes, spark_buckets, outcome_days,
                rich_mode, no_outcomes) -> None:
    ACTIONABLE = ["drip", "investigate", "qa"]
    if include_wait:
        ACTIONABLE = ACTIONABLE + ["retro"]

    # Two caps per station — queue (backpressure) vs in-flight (concurrency).
    # Queue cap = max backlog before we stop delivering. In-flight cap = max
    # parallel workers draining the inbox. None = unbounded.
    CAPS: dict[str, dict[str, int | None]] = {
        "qa":          {"queued": 3, "in_flight": 2},
        "drip":        {"queued": 5, "in_flight": 1},  # one push at a time
        "investigate": {"queued": 5, "in_flight": 3},
        "retro":       {"queued": None, "in_flight": None},  # unbounded batch
    }
    ACTION_HINT = {
        "qa":          "re-attest (CI failed / gates stale)",
        "drip":        "advance status (close / rebase / ship)",
        "investigate": "respond to maintainer",
        "retro":       "audit only (wait bucket)",
    }

    states: dict[str, dict[str, list[dict]]] = {}
    sections: dict[str, list[dict]] = {}  # unacked = queued + in_flight, for the per-item list
    for actor in ACTIONABLE:
        s = _inbox_states(actor)
        states[actor] = s
        sections[actor] = sorted(s["queued"] + s["in_flight"], key=lambda x: x.get("ts", ""))

    def _status_for(actor: str, queued: int, in_flight: int,
                    q_cap: int | None, f_cap: int | None) -> str:
        if queued + in_flight == 0:
            return "idle"
        flags = []
        if q_cap is not None and queued >= q_cap:
            flags.append(f"**queue capped** ({queued}/{q_cap})")
        if f_cap is not None and in_flight >= f_cap:
            flags.append(f"**in-flight capped** ({in_flight}/{f_cap})")
        if flags:
            return ", ".join(flags)
        if actor == "retro":
            return "history"
        if in_flight > 0:
            return "working"
        return "queued"

    rows: list[tuple[str, int, int, str, str, str, str, str]] = []
    for actor in ACTIONABLE:
        s = states[actor]
        queued = len(s["queued"])
        in_flight = len(s["in_flight"])
        q_cap = CAPS.get(actor, {}).get("queued")
        f_cap = CAPS.get(actor, {}).get("in_flight")
        # For the cockpit, throughput + variance live over the entire delivered
        # history of this actor (not just open msgs) — captures completed work too.
        all_msgs = s["queued"] + s["in_flight"] + s["done"]
        sparks = _bucketize(
            [m.get("ts", "") for m in all_msgs],
            spark_minutes, spark_buckets,
        )
        spark = _sparkline_pct(sparks, q_cap) or "·" * spark_buckets
        rate_h = _rate_per_hour(sparks, spark_minutes)
        rate_str = f"{rate_h:.1f}/h"
        var_glyph = _variance_glyph(sparks)
        rows.append((
            actor,
            queued,
            in_flight,
            rate_str,
            var_glyph,
            spark,
            _oldest_age_str(s["queued"] + s["in_flight"]),
            _status_for(actor, queued, in_flight, q_cap, f_cap),
        ))

    if rich_mode:
        _punch_rich(rows, sections, ACTIONABLE, ACTION_HINT, include_wait, spark_buckets)
        return

    # --- markdown output ----------------------------------------------------
    print("# coding factory — kanban")
    print()
    print("`intake: pr-state` (reads GitHub, classifies, routes by bucket) →")
    print()
    print(f"| station | queued | in-flight | rate | var | trend ({spark_minutes}m × {spark_buckets}, % of cap) | oldest | status |")
    print( "|---|---:|---:|---:|:-:|---|---|---|")
    for actor, queued, in_flight, rate_str, var_glyph, spark, oldest, status in rows:
        print(
            f"| → {actor} | {queued} | {in_flight} | {rate_str} | `{var_glyph}` "
            f"| `{spark}` | {oldest} | {status} |"
        )
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

    if not no_outcomes:
        o = _outcomes(outcome_days)
        merged = o["merged"]
        closed = o["closed"]
        total = merged + closed
        ratio = (merged / total * 100) if total else None
        days = o["days"]
        merge_dither = _dither(o["merged_per_day"])
        close_dither = _dither(o["closed_per_day"])
        # Day labels: oldest → newest, today is rightmost.
        end_date = dt.date.fromisoformat(o["end"])
        # Last-letter weekday for compact header (M T W T F S S).
        day_labels = "".join(
            (end_date - dt.timedelta(days=days - 1 - i)).strftime("%a")[0]
            for i in range(days)
        )

        print(f"## outcomes (last {days}d — what actually merged)")
        print()
        print(f"| metric | value |")
        print(f"|---|---:|")
        print(f"| merged | {merged} |")
        print(f"| closed (not merged) | {closed} |")
        if ratio is not None:
            print(f"| merge ratio | {ratio:.0f}% |")
        else:
            print(f"| merge ratio | — _(no outcomes)_ |")
        print(f"| daily merge rate | {merged / days:.1f} |")
        print()
        print("```")
        print(f"day   {day_labels}    ← oldest → today")
        print(f"merge {merge_dither}    {merged} total")
        print(f"close {close_dither}    {closed} total")
        print("```")
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
    for actor, queued, in_flight, rate_str, var_glyph, spark, oldest, status in rows:
        plain_status = status.replace("**", "")
        if "capped" in status:
            border, color = "red", "red bold"
        elif status == "idle":
            border, color = "green", "green"
        elif status == "history":
            border, color = "dim", "dim"
        elif status == "queued":
            border, color = "blue", "blue"
        else:
            border, color = "yellow", "yellow"
        body = Text()
        body.append("queued     ", style="dim"); body.append(f"{queued}\n", style="bold")
        body.append("in-flight  ", style="dim"); body.append(f"{in_flight}\n", style="bold")
        body.append("rate       ", style="dim"); body.append(f"{rate_str}\n", style="bold")
        body.append("var        ", style="dim"); body.append(f"{var_glyph}\n", style="bold")
        body.append(f"oldest     {oldest}\n", style="dim")
        body.append("trend      ", style="dim"); body.append(spark, style="cyan"); body.append("\n")
        body.append(plain_status, style=color)
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
