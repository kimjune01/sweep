"""`sweep up` / `sweep down` / `sweep status` — pipe lifecycle.

The pipe is the organism. `sweep up` spawns `temporal server start-dev`
and `sweep-worker` detached, writes their PIDs to ~/.sweep/control/,
and exits. `sweep down` SIGKILLs them. Idempotent in both directions.

Crashing is fine: Temporal preserves workflow state, the worker
re-registers when restarted. No graceful shutdown.

Callable from shell (remote sessions) or from sweep-tui — same code
path either way, so the TUI never owns lifecycle and the pipe
persists across TUI quit / SSH disconnect.
"""

from __future__ import annotations

import asyncio
import json as _json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import typer


CONTROL_DIR = Path.home() / ".sweep" / "control"
LOG_DIR = Path.home() / ".sweep" / "logs"

# (label, pid_filename, log_filename, argv, pgrep_pattern)
SERVICES = [
    ("temporal", "temporal.pid", "temporal.log",
     ["temporal", "server", "start-dev"], "temporal server start-dev"),
    ("worker", "worker.pid", "worker.log",
     ["sweep-worker"], "sweep-worker"),
]


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _read_pid(pid_file: Path) -> int | None:
    try:
        return int(pid_file.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def _reap_orphans(pattern: str, keep: int | None = None) -> None:
    try:
        out = subprocess.check_output(["pgrep", "-f", pattern], text=True)
    except subprocess.CalledProcessError:
        return
    except FileNotFoundError:
        return  # pgrep not installed (minimal containers); skip reap
    for line in out.splitlines():
        try:
            pid = int(line.strip())
        except ValueError:
            continue
        if pid == os.getpid() or pid == keep:
            continue
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _spawn(argv: list[str], log_file: Path) -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    # Worker subprocesses shell out to `cargo`, `npm`, `pnpm`, etc.
    # for per-repo builds. .zshrc isn't sourced for non-interactive
    # spawns, so we explicitly prepend the common toolchain bin dirs.
    # Otherwise rustup-installed `cargo` (29% of merge surface) is
    # invisible to qa/reqa cycles. Idempotent: missing dirs are
    # filtered before joining.
    env = os.environ.copy()
    toolchain_bins = [
        str(Path.home() / ".cargo" / "bin"),
        str(Path.home() / ".rustup" / "toolchains" / "stable-aarch64-apple-darwin" / "bin"),
        str(Path.home() / ".local" / "bin"),  # uv tool install (ruff, etc.)
        str(Path.home() / "Library" / "Python" / "3.9" / "bin"),  # pip --user
        str(Path.home() / "go" / "bin"),  # go install
        "/opt/homebrew/bin",
    ]
    extras = [p for p in toolchain_bins if Path(p).is_dir()]
    if extras:
        env["PATH"] = os.pathsep.join(extras + [env.get("PATH", "")])
    with open(log_file, "ab") as fh:
        proc = subprocess.Popen(
            argv,
            stdout=fh,
            stderr=fh,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            env=env,
        )
    return proc.pid


up_app = typer.Typer(help="Bring the pipe up (temporal + worker).", invoke_without_command=True)
down_app = typer.Typer(help="Bring the pipe down (SIGKILL temporal + worker).", invoke_without_command=True)
status_app = typer.Typer(help="Pipe status (temporal + worker).", invoke_without_command=True)


async def _ensure_actors(timeout_s: float = 15.0) -> tuple[list[str], list[str]]:
    """Idempotently start the long-running actor workflows. Polls
    temporal until reachable (the worker race means we can `sweep up`
    before temporal-dev has finished binding 7233), then calls
    start_workflow with swallowing of AlreadyStartedError.

    Returns (started, anomalies). `started` lists workflow ids freshly
    spawned this call; `anomalies` is human-readable status strings
    (skipped, already-running, errors).
    """
    from temporalio.client import Client
    from sweep.cli._common import (
        RESPOND_ACTOR_ID, INVESTIGATE_ACTOR_ID, LEAKDOG_DAEMON_ID,
        NOTIFICATION_POLLER_ID, SIFT_ACTOR_ID, QA_ACTOR_ID,
        BLESS_ACTOR_ID, BUG_REPORTER_ACTOR_ID, IMMUNIZE_ACTOR_ID, ROLL_ACTOR_ID, SWEEP_TASK_QUEUE,
        COMMENT_ISSUE_ACTOR_ID, TRIAGE_ACTOR_ID, USAGE_POLLER_ID, POST_ACTOR_ID,
        FILE_ISSUE_ACTOR_ID, SWITCH_ACTOR_ID,
        REMIT_ACTOR_ID, SUBMIT_ACTOR_ID, COMPOSE_ACTOR_ID, ROPE_ACTOR_ID,
        REINVESTIGATE_ACTOR_ID, REQA_ACTOR_ID, ATTEST_ACTOR_ID,
        AMEND_ACTOR_ID, HEART_ACTOR_ID, METRONOME_ACTOR_ID, RETRO_ACTOR_ID,
        CHECK_ACTOR_ID, PING_ACTOR_ID, SIGN_ACTOR_ID,
    )
    from sweep.system import TEMPORAL_ADDR
    from sweep.workflows.leakdog import LeakdogDaemon
    from sweep.workflows.notification_poller import NotificationPoller
    from sweep.workflows.metronome_actor import MetronomeActor
    from sweep.workflows.qa_actor import QaActor
    from sweep.workflows.skill_actor import SkillActor
    from sweep.workflows.usage_poller import UsagePoller

    deadline = time.monotonic() + timeout_s
    client = None
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            client = await Client.connect(TEMPORAL_ADDR)
            break
        except Exception as e:
            last_err = e
            await asyncio.sleep(0.5)
    if client is None:
        return [], [f"temporal unreachable ({last_err})"]

    started: list[str] = []
    anomalies: list[str] = []
    # (workflow_id, run-method, *args-to-run). SkillActor instances
    # share a class and differ only by id + activity_name passed to run.
    actors = [
        (QA_ACTOR_ID,           QaActor.run,        ()),
        (RESPOND_ACTOR_ID,         SkillActor.run,     ("respond_cycle",)),
        (REMIT_ACTOR_ID,           SkillActor.run,     ("remit_cycle",)),
        (SUBMIT_ACTOR_ID,          SkillActor.run,     ("submit_cycle",)),
        (COMPOSE_ACTOR_ID,         SkillActor.run,     ("compose_cycle",)),
        (ROPE_ACTOR_ID,            SkillActor.run,     ("rope_cycle",)),
        (TRIAGE_ACTOR_ID,       SkillActor.run,     ("triage_cycle",)),
        (INVESTIGATE_ACTOR_ID,  SkillActor.run,     ("investigate_cycle",)),
        (REINVESTIGATE_ACTOR_ID, SkillActor.run,    ("reinvestigate_cycle",)),
        (REQA_ACTOR_ID,         SkillActor.run,     ("reqa_cycle",)),
        (ATTEST_ACTOR_ID,       SkillActor.run,     ("attest_cycle",)),
        (AMEND_ACTOR_ID,        SkillActor.run,     ("amend_cycle",)),
        (CHECK_ACTOR_ID,        SkillActor.run,     ("check_cycle",)),
        (HEART_ACTOR_ID,        SkillActor.run,     ("heart_cycle",)),
        (PING_ACTOR_ID,         SkillActor.run,     ("ping_cycle",)),
        (SIGN_ACTOR_ID,         SkillActor.run,     ("sign_cycle",)),
        (METRONOME_ACTOR_ID,    MetronomeActor.run, ()),
        (RETRO_ACTOR_ID,        SkillActor.run,     ("retro_cycle",)),
        (SIFT_ACTOR_ID,        SkillActor.run,     ("sift_cycle",)),
        (ROLL_ACTOR_ID,        SkillActor.run,     ("roll_cycle",)),
        (COMMENT_ISSUE_ACTOR_ID,       SkillActor.run,     ("comment_issue_cycle",)),
        (POST_ACTOR_ID,         SkillActor.run,     ("post_cycle",)),
        (FILE_ISSUE_ACTOR_ID,   SkillActor.run,     ("file_issue_cycle",)),
        (SWITCH_ACTOR_ID,       SkillActor.run,     ("switch_cycle",)),
        (IMMUNIZE_ACTOR_ID,     SkillActor.run,     ("immunize_cycle",)),
        (BLESS_ACTOR_ID,        SkillActor.run,     ("bless_cycle",)),
        (BUG_REPORTER_ACTOR_ID, SkillActor.run,     ("bug_reporter_cycle",)),
        # Usage probing folded into metronome (5min cadence). Keeping
        # UsagePoller spawn commented for one cycle in case the new
        # metronome target needs a backout window; delete after.
        # (USAGE_POLLER_ID,       UsagePoller.run,    ()),
        (NOTIFICATION_POLLER_ID, NotificationPoller.run, ()),
        (LEAKDOG_DAEMON_ID,     LeakdogDaemon.run,  ()),
    ]
    for wf_id, run, run_args in actors:
        try:
            await client.start_workflow(
                run, args=list(run_args), id=wf_id, task_queue=SWEEP_TASK_QUEUE,
            )
            started.append(wf_id)
        except Exception as e:
            if "already started" in str(e).lower() or "AlreadyStartedError" in type(e).__name__:
                anomalies.append(f"{wf_id}: already running")
            else:
                anomalies.append(f"{wf_id}: {e}")

    # Drain pending inboxes into the (possibly fresh) actor queues.
    # Without this, every restart leaves the disk-backed records
    # disconnected from the in-memory actor — operator sees `queued: N`
    # in cockpit but actor depth=0 and nothing moves. Re-signaling is
    # idempotent (deliver dedupes by msg_id).
    drained = await _drain_inbox(client, "qa", QaActor.deliver, QA_ACTOR_ID)
    if drained:
        anomalies.append(f"{QA_ACTOR_ID}: drained {drained} pending")
    drained = await _drain_inbox(client, "respond", SkillActor.deliver, RESPOND_ACTOR_ID)
    if drained:
        anomalies.append(f"{RESPOND_ACTOR_ID}: drained {drained} pending")
    drained = await _drain_inbox(client, "remit", SkillActor.deliver, REMIT_ACTOR_ID)
    if drained:
        anomalies.append(f"{REMIT_ACTOR_ID}: drained {drained} pending")
    drained = await _drain_inbox(client, "submit", SkillActor.deliver, SUBMIT_ACTOR_ID)
    if drained:
        anomalies.append(f"{SUBMIT_ACTOR_ID}: drained {drained} pending")
    drained = await _drain_inbox(client, "compose", SkillActor.deliver, COMPOSE_ACTOR_ID)
    if drained:
        anomalies.append(f"{COMPOSE_ACTOR_ID}: drained {drained} pending")
    drained = await _drain_inbox(client, "rope", SkillActor.deliver, ROPE_ACTOR_ID)
    if drained:
        anomalies.append(f"{ROPE_ACTOR_ID}: drained {drained} pending")
    drained = await _drain_inbox(client, "triaged", SkillActor.deliver, TRIAGE_ACTOR_ID)
    if drained:
        anomalies.append(f"{TRIAGE_ACTOR_ID}: drained {drained} pending")
    drained = await _drain_inbox(client, "investigate", SkillActor.deliver, INVESTIGATE_ACTOR_ID)
    if drained:
        anomalies.append(f"{INVESTIGATE_ACTOR_ID}: drained {drained} pending")
    drained = await _drain_inbox(client, "reinvestigate", SkillActor.deliver, REINVESTIGATE_ACTOR_ID)
    if drained:
        anomalies.append(f"{REINVESTIGATE_ACTOR_ID}: drained {drained} pending")
    drained = await _drain_inbox(client, "reqa", SkillActor.deliver, REQA_ACTOR_ID)
    if drained:
        anomalies.append(f"{REQA_ACTOR_ID}: drained {drained} pending")
    drained = await _drain_inbox(client, "attest", SkillActor.deliver, ATTEST_ACTOR_ID)
    if drained:
        anomalies.append(f"{ATTEST_ACTOR_ID}: drained {drained} pending")
    drained = await _drain_inbox(client, "amend", SkillActor.deliver, AMEND_ACTOR_ID)
    if drained:
        anomalies.append(f"{AMEND_ACTOR_ID}: drained {drained} pending")
    drained = await _drain_inbox(client, "heart", SkillActor.deliver, HEART_ACTOR_ID)
    if drained:
        anomalies.append(f"{HEART_ACTOR_ID}: drained {drained} pending")
    drained = await _drain_inbox(client, "metronome", MetronomeActor.deliver, METRONOME_ACTOR_ID)
    if drained:
        anomalies.append(f"{METRONOME_ACTOR_ID}: drained {drained} pending")
    drained = await _drain_inbox(client, "retro", SkillActor.deliver, RETRO_ACTOR_ID)
    if drained:
        anomalies.append(f"{RETRO_ACTOR_ID}: drained {drained} pending")
    drained = await _drain_inbox(client, "sift", SkillActor.deliver, SIFT_ACTOR_ID)
    if drained:
        anomalies.append(f"{SIFT_ACTOR_ID}: drained {drained} pending")
    drained = await _drain_inbox(client, "roll", SkillActor.deliver, ROLL_ACTOR_ID)
    if drained:
        anomalies.append(f"{ROLL_ACTOR_ID}: drained {drained} pending")
    drained = await _drain_inbox(client, "comment-issue", SkillActor.deliver, COMMENT_ISSUE_ACTOR_ID)
    if drained:
        anomalies.append(f"{COMMENT_ISSUE_ACTOR_ID}: drained {drained} pending")
    drained = await _drain_inbox(client, "post", SkillActor.deliver, POST_ACTOR_ID)
    if drained:
        anomalies.append(f"{POST_ACTOR_ID}: drained {drained} pending")
    drained = await _drain_inbox(client, "file-issue", SkillActor.deliver, FILE_ISSUE_ACTOR_ID)
    if drained:
        anomalies.append(f"{FILE_ISSUE_ACTOR_ID}: drained {drained} pending")
    drained = await _drain_inbox(client, "switch", SkillActor.deliver, SWITCH_ACTOR_ID)
    if drained:
        anomalies.append(f"{SWITCH_ACTOR_ID}: drained {drained} pending")
    drained = await _drain_inbox(client, "immunize", SkillActor.deliver, IMMUNIZE_ACTOR_ID)
    if drained:
        anomalies.append(f"{IMMUNIZE_ACTOR_ID}: drained {drained} pending")
    drained = await _drain_inbox(client, "bless", SkillActor.deliver, BLESS_ACTOR_ID)
    if drained:
        anomalies.append(f"{BLESS_ACTOR_ID}: drained {drained} pending")
    drained = await _drain_inbox(client, "bug-reporter", SkillActor.deliver, BUG_REPORTER_ACTOR_ID)
    if drained:
        anomalies.append(f"{BUG_REPORTER_ACTOR_ID}: drained {drained} pending")
    return started, anomalies


async def _drain_inbox(client, actor: str, deliver_method, wf_id: str) -> int:
    """Signal every unacked message in <actor>.jsonl to the actor.
    Returns count signaled. Idempotent at the actor (msg_id dedup)."""
    import json as _json
    from sweep.inbox_state import INBOX_DIR, load_msg_id_set
    from sweep.types import Message as _Msg
    import datetime as _dt

    path = INBOX_DIR / f"{actor}.jsonl"
    if not path.exists():
        return 0
    acked = load_msg_id_set(INBOX_DIR / "_acks.jsonl")
    handle = client.get_workflow_handle(wf_id)
    sent = 0
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            d = _json.loads(line)
        except _json.JSONDecodeError:
            continue
        mid = d.get("msg_id", "")
        if not mid or mid in acked:
            continue
        msg = _Msg(
            msg_id=mid,
            sender=d.get("sender", "drain"),
            intent=d.get("intent", ""),
            repo=d.get("repo", ""),
            pr=d.get("pr"),
            branch=d.get("branch") or "",
            payload=d.get("payload", {}),
            ts=d.get("ts", _dt.datetime.now(_dt.timezone.utc).isoformat()),
            ledger=d.get("ledger") or [],
        )
        try:
            await handle.signal(deliver_method, msg)
            sent += 1
        except Exception as e:
            from sweep import observe
            observe.event("drain_signal_failed", actor=actor, wf_id=wf_id,
                          msg_id=mid, error_type=type(e).__name__,
                          error=str(e)[:300])
    return sent


@up_app.callback(invoke_without_command=True)
def up(json: bool = typer.Option(False, "--json", help="Emit machine-readable state per service.")) -> None:
    """Idempotent. Reap orphans, spawn anything missing, write PIDs.

    With ``--json``, emits ``{label: {state, pid}}`` where ``state`` is
    one of ``started`` / ``already_running`` / ``skipped``. The TUI uses
    this to track which services it brought up so it knows what to tear
    down on quit (versus what it found and shouldn't touch).
    """
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    result: dict[str, dict[str, object]] = {}
    for label, pid_name, log_name, argv, pattern in SERVICES:
        pid_file = CONTROL_DIR / pid_name
        pid = _read_pid(pid_file)
        if pid and _alive(pid):
            result[label] = {"state": "already_running", "pid": pid}
            if not json:
                print(f"{label}: already running (pid {pid})")
            continue
        if shutil.which(argv[0]) is None:
            result[label] = {"state": "skipped", "reason": f"{argv[0]} not on PATH"}
            if not json:
                print(f"{label}: {argv[0]} not on PATH (skip)")
            continue
        _reap_orphans(pattern)
        new_pid = _spawn(argv, LOG_DIR / log_name)
        pid_file.write_text(f"{new_pid}\n")
        result[label] = {"state": "started", "pid": new_pid, "log": str(LOG_DIR / log_name)}
        if not json:
            print(f"{label}: started (pid {new_pid}, log {LOG_DIR / log_name})")
    # Idempotent actor bootstrap. The worker is now polling sweep-tq,
    # so any actor workflow we start will be picked up immediately. We
    # poll temporal for reachability inside _ensure_actors because
    # temporal-dev binds 7233 a beat after `temporal server start-dev`
    # returns from spawn.
    actor_state: dict[str, object] = {"started": [], "anomalies": []}
    if result.get("worker", {}).get("state") in ("started", "already_running"):
        try:
            started, anomalies = asyncio.run(_ensure_actors())
            actor_state = {"started": started, "anomalies": anomalies}
            if not json:
                for wf_id in started:
                    print(f"{wf_id}: started")
                for line in anomalies:
                    print(line)
        except Exception as e:
            actor_state = {"started": [], "anomalies": [f"actor bootstrap: {e}"]}
            if not json:
                print(f"actor bootstrap: {e}")
    result["_actors"] = actor_state

    if json:
        print(_json.dumps(result))


@down_app.callback(invoke_without_command=True)
def down() -> None:
    """SIGKILL temporal + worker, remove PID files, reap stragglers."""
    for label, pid_name, _log_name, _argv, pattern in SERVICES:
        pid_file = CONTROL_DIR / pid_name
        pid = _read_pid(pid_file)
        if pid and _alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
                print(f"{label}: killed (pid {pid})")
            except ProcessLookupError:
                pass
        else:
            print(f"{label}: not running")
        pid_file.unlink(missing_ok=True)
        # Safety net: kill anything matching the signature that wasn't
        # tracked in the PID file (e.g. started manually).
        _reap_orphans(pattern)


@status_app.callback(invoke_without_command=True)
def status() -> None:
    """One line per service: pid + alive?"""
    for label, pid_name, _log_name, _argv, _pattern in SERVICES:
        pid = _read_pid(CONTROL_DIR / pid_name)
        if pid and _alive(pid):
            print(f"{label}: up (pid {pid})")
        elif pid:
            print(f"{label}: stale pid {pid}")
        else:
            print(f"{label}: down")
