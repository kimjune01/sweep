"""broom — periodic file-system sweep, 5S for the substrate.

Every actor paradigm needs a broom: JSONL files grow unbounded unless
something prunes them. This module is that something. Each file type has
its own retention policy because they answer different questions over
different time windows; one-size-fits-all retention would either keep too
little (breaks retro) or too much (breaks read latency).

Policies (defaults; tunable via ~/.sweep/control/retain/<name>):

  inbox/<actor>.jsonl    drop messages whose msg_id appears in _acks.jsonl
                         (tombstone-based, not time-based — unacked work
                         is load-bearing regardless of age)
  inbox/_acks.jsonl      drop msg_ids no longer present in any inbox
  inbox/_started.jsonl   same as _acks
  events.jsonl           keep 7d (cockpit/waste only look at 1h; retro
                         and hansei want a week of pattern history)
  sink.jsonl             keep 90d (audit log — "why did we evict X")
  logs/worker.log        rotate at 50MB → .1 (size-based; tail-friendly)
  logs/temporal.log      same
  budget/*.jsonl         keep 30d (monthly spend rollups need a month)

Race-safety: each file is rewritten via tmp + rename. Writers appending
during the rewrite window may have their lines lost if they land between
our read and the rename. At sweep's write rate (a few/sec) and broom's
cadence (daily), the loss window is microseconds — acceptable. If this
ever bites, pause the line before brooming.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

SWEEP_HOME = Path.home() / ".sweep"
INBOX_DIR = SWEEP_HOME / "inbox"
LOGS_DIR = SWEEP_HOME / "logs"
BUDGET_DIR = SWEEP_HOME / "budget"
EVENTS_FILE = SWEEP_HOME / "events.jsonl"
SINK_FILE = INBOX_DIR / "sink.jsonl"
ACKS_FILE = INBOX_DIR / "_acks.jsonl"
STARTED_FILE = INBOX_DIR / "_started.jsonl"
RETAIN_DIR = SWEEP_HOME / "control" / "retain"

LOG_ROTATE_BYTES = 50 * 1024 * 1024


@dataclass
class SweepResult:
    """Per-file outcome from one broom pass."""
    path: Path
    policy: str
    before_bytes: int
    after_bytes: int
    before_lines: int
    after_lines: int
    dropped: int
    dry_run: bool

    @property
    def reclaimed_bytes(self) -> int:
        return max(0, self.before_bytes - self.after_bytes)


def _read_retain(name: str, default_days: int) -> int:
    """Read per-file retention override (days). Falls back to default."""
    p = RETAIN_DIR / name
    try:
        return max(1, int(p.read_text().strip()))
    except (OSError, ValueError):
        return default_days


def _stat(path: Path) -> tuple[int, int]:
    """Return (bytes, lines). (0, 0) if file missing."""
    if not path.exists():
        return 0, 0
    try:
        b = path.stat().st_size
        n = sum(1 for ln in path.read_text().splitlines() if ln.strip())
        return b, n
    except OSError:
        return 0, 0


def _atomic_rewrite(path: Path, keep_lines: list[str], dry_run: bool) -> None:
    """Write keep_lines to path via tmp + rename. Preserves file mode.
    Dry-run skips the rename so callers can compute the would-be result."""
    if dry_run:
        return
    tmp = path.with_suffix(path.suffix + ".broom-tmp")
    try:
        mode = path.stat().st_mode
    except OSError:
        mode = 0o644
    try:
        tmp.write_text("\n".join(keep_lines) + ("\n" if keep_lines else ""))
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _load_msg_ids(path: Path) -> set[str]:
    """msg_id set from a jsonl ledger. Empty set on read failure."""
    out: set[str] = set()
    if not path.exists():
        return out
    try:
        for ln in path.read_text().splitlines():
            if not ln.strip():
                continue
            try:
                d = json.loads(ln)
            except json.JSONDecodeError:
                continue
            mid = d.get("msg_id")
            if mid:
                out.add(mid)
    except OSError:
        pass
    return out


def _sweep_inbox(path: Path, acked: set[str], dry_run: bool) -> SweepResult:
    """Drop acked entries from an actor inbox. Tombstone-based: unacked
    messages stay regardless of age (they're work in flight)."""
    before_bytes, before_lines = _stat(path)
    if before_lines == 0:
        return SweepResult(path, "drop-acked", before_bytes, before_bytes,
                           0, 0, 0, dry_run)
    keep: list[str] = []
    dropped = 0
    for ln in path.read_text().splitlines():
        if not ln.strip():
            continue
        try:
            d = json.loads(ln)
        except json.JSONDecodeError:
            keep.append(ln)  # preserve malformed lines for inspection
            continue
        mid = d.get("msg_id")
        if mid and mid in acked:
            dropped += 1
        else:
            keep.append(ln)
    _atomic_rewrite(path, keep, dry_run)
    after_bytes = sum(len(ln) + 1 for ln in keep) if not dry_run else (
        sum(len(ln) + 1 for ln in keep))
    return SweepResult(path, "drop-acked", before_bytes, after_bytes,
                       before_lines, len(keep), dropped, dry_run)


def _sweep_ledger_keep_referenced(path: Path, live_ids: set[str],
                                   dry_run: bool) -> SweepResult:
    """For _acks.jsonl / _started.jsonl: keep entries whose msg_id is still
    referenced in some inbox; drop the rest (dangling tombstones)."""
    before_bytes, before_lines = _stat(path)
    if before_lines == 0:
        return SweepResult(path, "drop-dangling", before_bytes, before_bytes,
                           0, 0, 0, dry_run)
    keep: list[str] = []
    dropped = 0
    for ln in path.read_text().splitlines():
        if not ln.strip():
            continue
        try:
            d = json.loads(ln)
        except json.JSONDecodeError:
            keep.append(ln)
            continue
        mid = d.get("msg_id")
        if mid and mid in live_ids:
            keep.append(ln)
        else:
            dropped += 1
    _atomic_rewrite(path, keep, dry_run)
    after_bytes = sum(len(ln) + 1 for ln in keep)
    return SweepResult(path, "drop-dangling", before_bytes, after_bytes,
                       before_lines, len(keep), dropped, dry_run)


def _sweep_by_age(path: Path, days: int, policy_name: str,
                   dry_run: bool) -> SweepResult:
    """Drop jsonl lines whose `ts` (ISO 8601) is older than `days` days.
    Lines without a parseable ts are kept (no opinion about their age)."""
    before_bytes, before_lines = _stat(path)
    if before_lines == 0:
        return SweepResult(path, policy_name, before_bytes, before_bytes,
                           0, 0, 0, dry_run)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    keep: list[str] = []
    dropped = 0
    for ln in path.read_text().splitlines():
        if not ln.strip():
            continue
        try:
            d = json.loads(ln)
        except json.JSONDecodeError:
            keep.append(ln)
            continue
        ts_str = d.get("ts") or d.get("timestamp") or ""
        keep_it = True
        if ts_str:
            try:
                t = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
                if t < cutoff:
                    keep_it = False
            except (ValueError, TypeError):
                pass
        if keep_it:
            keep.append(ln)
        else:
            dropped += 1
    _atomic_rewrite(path, keep, dry_run)
    after_bytes = sum(len(ln) + 1 for ln in keep)
    return SweepResult(path, policy_name, before_bytes, after_bytes,
                       before_lines, len(keep), dropped, dry_run)


def _rotate_log(path: Path, dry_run: bool) -> SweepResult:
    """Rotate a log file: when > LOG_ROTATE_BYTES, mv to .1 (replacing
    any existing .1) and truncate the original. Two-generation retention
    is enough for ad-hoc debugging; older history isn't useful."""
    before_bytes, before_lines = _stat(path)
    if before_bytes <= LOG_ROTATE_BYTES:
        return SweepResult(path, "rotate-size", before_bytes, before_bytes,
                           before_lines, before_lines, 0, dry_run)
    if dry_run:
        return SweepResult(path, "rotate-size", before_bytes, 0,
                           before_lines, 0, before_lines, dry_run)
    backup = path.with_suffix(path.suffix + ".1")
    try:
        if backup.exists():
            backup.unlink()
        shutil.move(str(path), str(backup))
        path.touch()
    except OSError:
        return SweepResult(path, "rotate-size", before_bytes, before_bytes,
                           before_lines, before_lines, 0, dry_run)
    return SweepResult(path, "rotate-size", before_bytes, 0,
                       before_lines, 0, before_lines, dry_run)


def sweep_all(dry_run: bool = False) -> list[SweepResult]:
    """Run every policy. Returns one SweepResult per file touched, in
    sweep order so callers can render a per-file before/after table."""
    results: list[SweepResult] = []

    # 1. Inboxes — drop acked. Done first because it shrinks the set of
    # live msg_ids that the ledger sweep references.
    acked = _load_msg_ids(ACKS_FILE)
    if INBOX_DIR.exists():
        for p in sorted(INBOX_DIR.iterdir()):
            if not p.is_file() or not p.name.endswith(".jsonl"):
                continue
            if p.name.startswith("_") or p.name == "sink.jsonl":
                continue
            results.append(_sweep_inbox(p, acked, dry_run))

    # 2. _acks / _started — drop entries no longer referenced by any inbox.
    # Live set = current inbox msg_ids MINUS acked. This is what the inbox
    # *would* hold post-sweep, so the dry-run projection matches reality
    # regardless of whether the inbox rewrite actually happened.
    live: set[str] = set()
    if INBOX_DIR.exists():
        for p in INBOX_DIR.iterdir():
            if not p.is_file() or not p.name.endswith(".jsonl"):
                continue
            if p.name.startswith("_"):
                continue
            live |= _load_msg_ids(p)
    live -= acked
    for ledger in (ACKS_FILE, STARTED_FILE):
        if ledger.exists():
            results.append(_sweep_ledger_keep_referenced(ledger, live, dry_run))

    # 3. events.jsonl — age-based (7d default).
    if EVENTS_FILE.exists():
        days = _read_retain("events", 7)
        results.append(_sweep_by_age(EVENTS_FILE, days, f"age-{days}d", dry_run))

    # 4. sink.jsonl — long audit retention (90d).
    if SINK_FILE.exists():
        days = _read_retain("sink", 90)
        results.append(_sweep_by_age(SINK_FILE, days, f"age-{days}d", dry_run))

    # 5. budget/*.jsonl — 30d.
    if BUDGET_DIR.exists():
        days = _read_retain("budget", 30)
        for p in sorted(BUDGET_DIR.iterdir()):
            if p.is_file() and p.name.endswith(".jsonl"):
                results.append(_sweep_by_age(p, days, f"age-{days}d", dry_run))

    # 6. Logs — size-based rotation.
    if LOGS_DIR.exists():
        for p in sorted(LOGS_DIR.iterdir()):
            if p.is_file() and p.name.endswith(".log"):
                results.append(_rotate_log(p, dry_run))

    return results


def sweep_one(name: str, dry_run: bool = False) -> list[SweepResult]:
    """Run a single named policy. `name` matches a file path under
    ~/.sweep/ (e.g. 'inbox/sift.jsonl', 'events.jsonl', 'logs/worker.log')."""
    p = SWEEP_HOME / name
    if not p.exists():
        raise FileNotFoundError(f"{p} not found")
    if p.parent == INBOX_DIR and not p.name.startswith("_") and p.name != "sink.jsonl":
        acked = _load_msg_ids(ACKS_FILE)
        return [_sweep_inbox(p, acked, dry_run)]
    if p == ACKS_FILE or p == STARTED_FILE:
        live: set[str] = set()
        for q in INBOX_DIR.iterdir():
            if q.is_file() and q.name.endswith(".jsonl") and not q.name.startswith("_"):
                live |= _load_msg_ids(q)
        return [_sweep_ledger_keep_referenced(p, live, dry_run)]
    if p == EVENTS_FILE:
        return [_sweep_by_age(p, _read_retain("events", 7), "age-events", dry_run)]
    if p == SINK_FILE:
        return [_sweep_by_age(p, _read_retain("sink", 90), "age-sink", dry_run)]
    if p.parent == BUDGET_DIR:
        return [_sweep_by_age(p, _read_retain("budget", 30), "age-budget", dry_run)]
    if p.parent == LOGS_DIR:
        return [_rotate_log(p, dry_run)]
    raise ValueError(f"no broom policy for {p}")


# ---------------------------------------------------------------- disk


WORKTREES_DIR = SWEEP_HOME / "worktrees"
BUILD_CACHE_DIR = SWEEP_HOME / "build-cache"


@dataclass
class DiskResult:
    """Per-action outcome from one disk-broom pass."""
    target: str          # "worktree:<repo>" / "build-cache:<repo>" / "docker"
    reason: str          # why we're dropping it
    bytes_reclaimed: int
    dry_run: bool


def _du_bytes(path: Path) -> int:
    """Total bytes under path. Cheap shell out to du -sk."""
    import subprocess as _sp
    try:
        r = _sp.run(["du", "-sk", str(path)],
                    capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            return 0
        return int(r.stdout.split()[0]) * 1024
    except (FileNotFoundError, _sp.TimeoutExpired, ValueError, IndexError):
        return 0


def _evicted_repos() -> set[str]:
    """Read the eviction list as a set of repo slugs (owner/repo)."""
    p = SWEEP_HOME / "control" / "sift_evicted.txt"
    if not p.exists():
        return set()
    out: set[str] = set()
    for ln in p.read_text().splitlines():
        # Lines like "owner/repo  # comment" -- take the first token.
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        token = ln.split()[0] if ln.split() else ""
        if "/" in token:
            out.add(token)
    return out


def disk_sweep(dry_run: bool = False) -> list[DiskResult]:
    """Reclaim disk that's redundant with the current substrate state:

      1. Worktrees of evicted repos -- we'll never run tests there
         again; the clone is dead weight.
      2. Build-cache dirs for evicted repos -- same reason.
      3. Docker dangling images / containers / volumes older than 24h.
         (24h filter preserves sweep-tester:latest between rebuilds.)

    Returns a list of DiskResult per action so the CLI can show what
    moved. Dry-run computes sizes but touches nothing."""
    import subprocess as _sp
    results: list[DiskResult] = []
    evicted = _evicted_repos()

    # Worktrees + build-cache for evicted repos.
    for root, kind in ((WORKTREES_DIR, "worktree"),
                       (BUILD_CACHE_DIR, "build-cache")):
        if not root.exists():
            continue
        for d in sorted(root.iterdir()):
            if not d.is_dir():
                continue
            # On-disk slug is "owner__repo"; the eviction list uses "owner/repo".
            repo = d.name.replace("__", "/", 1)
            if repo not in evicted:
                continue
            size = _du_bytes(d)
            if not dry_run:
                shutil.rmtree(d, ignore_errors=True)
            results.append(DiskResult(
                target=f"{kind}:{repo}",
                reason="repo is on eviction list",
                bytes_reclaimed=size, dry_run=dry_run,
            ))

    # Docker prune (older than 24h to preserve sweep-tester:latest).
    if shutil.which("docker"):
        if dry_run:
            try:
                r = _sp.run(["docker", "system", "df", "--format", "json"],
                            capture_output=True, text=True, timeout=5)
                reclaim = 0
                if r.returncode == 0:
                    for line in r.stdout.splitlines():
                        try:
                            d = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        s = (d.get("Reclaimable") or "").split(" ", 1)[0]
                        for u, m in (("GB", 1024**3), ("MB", 1024**2),
                                     ("KB", 1024), ("B", 1)):
                            if s.endswith(u):
                                try:
                                    reclaim += int(float(s[:-len(u)]) * m)
                                except ValueError:
                                    pass
                                break
                results.append(DiskResult(
                    target="docker", reason="dangling >24h",
                    bytes_reclaimed=reclaim, dry_run=True,
                ))
            except (_sp.TimeoutExpired, OSError):
                pass
        else:
            try:
                r = _sp.run(
                    ["docker", "system", "prune", "-af", "--volumes",
                     "--filter", "until=24h"],
                    capture_output=True, text=True, timeout=120,
                )
                reclaim = 0
                for line in (r.stdout or "").splitlines():
                    if line.startswith("Total reclaimed space:"):
                        s = line.split(":", 1)[1].strip().split()[0]
                        for u, m in (("GB", 1024**3), ("MB", 1024**2),
                                     ("kB", 1024), ("B", 1)):
                            if s.endswith(u):
                                try:
                                    reclaim = int(float(s[:-len(u)]) * m)
                                except ValueError:
                                    pass
                                break
                results.append(DiskResult(
                    target="docker", reason="dangling >24h",
                    bytes_reclaimed=reclaim, dry_run=False,
                ))
            except (_sp.TimeoutExpired, OSError):
                pass

    return results


def summary(results: list[SweepResult]) -> dict:
    """Aggregate stats for observe events / metronome reporting."""
    return {
        "files_touched": sum(1 for r in results if r.dropped > 0),
        "files_scanned": len(results),
        "lines_dropped": sum(r.dropped for r in results),
        "bytes_reclaimed": sum(r.reclaimed_bytes for r in results),
    }
