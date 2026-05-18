"""Probe Claude Code's /usage slash command and write parsed JSON.

Drives `claude` via pexpect (need a pty — slash commands only fire in
the interactive UI), waits for the prompt to settle, types /usage,
captures the status-dialog text, dismisses, exits.

Output: ~/.sweep/control/claude_usage.json with the parsed numbers
plus a `parse_ok` flag. If parse fails, the activity raises
ApplicationError and the UsagePoller's andon catches it — better to
halt and surface the format change than silently report stale data.

Format-fragility: the parser depends on the prose layout of the
status dialog (e.g. lines like "Current 5h window: 67%"). Claude
Code version bumps can shift the layout. Andon-on-format-change
means the operator notices the parser is stale within one cycle
rather than weeks later.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path

from temporalio import activity
from temporalio.exceptions import ApplicationError


OUTPUT_PATH = Path.home() / ".sweep" / "control" / "claude_usage.json"

# Patterns the parser looks for. Anchored loosely; the slash-command
# output uses prose like "Current 5h window: 67%" — be tolerant of
# extra punctuation, ANSI escapes (stripped before match), and order.
_PERCENT_RE = re.compile(r"(\d{1,3})\s*%")
_ANSI_RE = re.compile(r"\x1b\[[\d;?]*[A-Za-z]|\x1b\][^\x07]*\x07")


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


def _parse_usage(raw: str) -> dict:
    """Walk the de-ANSI'd output, attach percentages to their preceding
    label. The current /usage panel looks like:

        Current session
          ██████                                    12% used
          Resets 7pm (America/Vancouver)
        Current week (all models)
          █████████▌                                19% used
          Resets May 22 at 3am (America/Vancouver)

    Strategy: track the most recent header-ish line seen, attach the
    next percent to it. "session" → session_pct (5h subscription
    window), "week" → week_pct (weekly cap).
    """
    text = _strip_ansi(raw)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    out: dict = {"raw_lines": lines[-40:]}  # keep recent context for debug
    label: str | None = None
    for ln in lines:
        low = ln.lower()
        # Headers don't contain a percent themselves; track them as
        # "where the next percent belongs."
        if "session" in low and "%" not in ln:
            label = "session_pct"
            continue
        if "week" in low and "%" not in ln:
            label = "week_pct"
            continue
        m = _PERCENT_RE.search(ln)
        if not m:
            continue
        pct = int(m.group(1))
        if label and label not in out:
            out[label] = pct
            label = None  # consume; next header will reset
    if "session_pct" not in out and "week_pct" not in out:
        raise ApplicationError(
            f"usage probe: no percent fields recognized in /usage output "
            f"(first 5 lines: {lines[:5]})",
            non_retryable=True,
        )
    return out


def _probe_blocking(timeout_s: int) -> str:
    """Synchronous pexpect interaction. Blocks ~10s on pty I/O; run
    via asyncio.to_thread so the worker's event loop keeps polling/
    heartbeating actors while we wait.

    Capture pattern: poll `read_nonblocking` in 200ms slices and
    accumulate the chunks. The original implementation called
    `read_nonblocking` once and inspected `child.before`, which is
    empty without a matching `expect` — the bug that produced the
    persistent "no percent fields recognized" flakes.
    """
    import pexpect

    # Larger window — /usage panel needs vertical room or it collapses
    # into the autocomplete tooltip rather than rendering the dialog.
    child = pexpect.spawn("claude", encoding="utf-8", timeout=timeout_s,
                          dimensions=(80, 220))
    chunks: list[str] = []

    def _drain(seconds: float) -> None:
        """Read everything currently in the pty + anything that arrives
        within `seconds`. Returns when no data has arrived for 200ms."""
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                data = child.read_nonblocking(size=65536, timeout=0.2)
            except pexpect.TIMEOUT:
                # No more data this tick. Keep trying until deadline.
                continue
            except (pexpect.EOF, Exception):
                return
            if data:
                chunks.append(data)
                # Extend the deadline a bit so a slow render finishes.
                deadline = max(deadline, time.time() + 0.5)

    try:
        # Welcome screen + plugin list render ~3-4s on first paint.
        _drain(4)
        # Type /usage one char at a time so the slash-command
        # autocomplete picks it up cleanly. Bulk `send("/usage")`
        # races the autocomplete and Enter can select the wrong
        # menu entry. Per-char + small intra-char sleeps lets the
        # UI settle on the /usage entry as the active match.
        for ch in "/usage":
            child.send(ch)
            time.sleep(0.05)
        time.sleep(0.4)
        # Dismiss the autocomplete dropdown (Tab would accept, ESC
        # closes it leaving the typed text in the prompt), then Enter
        # to submit the command. Without the dismissal, the first
        # Enter selects the highlighted suggestion (which is
        # `/usage` itself but the UI sometimes mis-handles this).
        child.sendcontrol("[")
        time.sleep(0.2)
        child.sendcontrol("m")  # Enter — submits /usage
        # /usage dialog renders within 2-3s, then sits. Drain longer
        # since the panel grows incrementally.
        _drain(6)
        # Dismiss the dialog so the next /exit lands cleanly.
        child.sendcontrol("[")  # ESC
        time.sleep(0.3)
        child.send("/exit")
        child.sendcontrol("m")
    finally:
        try:
            child.close(force=True)
        except Exception:
            pass
    return "".join(chunks)


@activity.defn
async def probe_claude_usage(timeout_s: int = 30) -> dict:
    """Spawn claude, send /usage, capture, write JSON when we get a
    parseable answer. Tolerate flakiness — the /usage panel sometimes
    returns nothing, and the right shape is "keep the last good value
    on disk; don't halt the actor on a single blank probe." The
    wasteboard reads the cached value with a freshness tag.

    Returns the parsed dict on success or {"parse_ok": false, ...} on
    a flake. Raises only on driver-level failures (pexpect missing,
    claude binary missing) — those are substrate, not noise.
    """
    try:
        import pexpect  # noqa: F401 — import check before threading
    except ImportError as e:
        raise ApplicationError(f"usage probe: pexpect missing ({e})",
                               non_retryable=True)
    raw = await asyncio.to_thread(_probe_blocking, timeout_s)
    try:
        parsed = _parse_usage(raw)
    except ApplicationError as e:
        # Flaky empty / unrecognized output → don't andon, don't
        # overwrite the cache. Let the wasteboard's freshness check
        # surface the staleness if it persists.
        from sweep import observe
        observe.event("usage_probe_flake", reason=str(e.message or "")[:200])
        return {"parse_ok": False, "reason": str(e.message or "")[:200]}
    parsed["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    parsed["parse_ok"] = True
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(parsed, indent=2) + "\n")
    return parsed
