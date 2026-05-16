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
    """Walk the de-ANSI'd output line by line, attach percentages to
    nearby labels. Returns at minimum `{five_hour_pct, weekly_pct}`
    when both are present; raises if neither is parseable."""
    text = _strip_ansi(raw)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    out: dict = {"raw_lines": lines[-40:]}  # keep recent context for debug
    for i, ln in enumerate(lines):
        low = ln.lower()
        m = _PERCENT_RE.search(ln)
        if not m:
            continue
        pct = int(m.group(1))
        if "5h" in low or "5-hour" in low or "five hour" in low or "current" in low:
            out.setdefault("five_hour_pct", pct)
        elif "week" in low:
            out.setdefault("weekly_pct", pct)
    if "five_hour_pct" not in out and "weekly_pct" not in out:
        raise ApplicationError(
            f"usage probe: no percent fields recognized in /usage output "
            f"(first 5 lines: {lines[:5]})",
            non_retryable=True,
        )
    return out


def _probe_blocking(timeout_s: int) -> str:
    """Synchronous pexpect interaction. Blocks ~6s on time.sleeps and
    pty I/O; run via asyncio.to_thread so the worker's event loop keeps
    polling/heartbeating actors while we wait."""
    import pexpect

    child = pexpect.spawn("claude", encoding="utf-8", timeout=timeout_s,
                          dimensions=(50, 200))
    captured: list[str] = []
    try:
        time.sleep(2)
        child.send("/usage")
        time.sleep(0.5)
        child.sendcontrol("m")  # Enter
        time.sleep(3)
        try:
            child.read_nonblocking(size=65536, timeout=2)
        except Exception:
            pass
        captured.append(child.before or "")
        captured.append(child.buffer or "")
        child.sendcontrol("[")  # ESC
        time.sleep(0.3)
        child.send("/exit")
        child.sendcontrol("m")
    finally:
        try:
            child.close(force=True)
        except Exception:
            pass
    return "".join(captured)


@activity.defn
async def probe_claude_usage(timeout_s: int = 30) -> dict:
    """Spawn claude, send /usage, capture, write JSON. Returns the
    parsed dict on success; raises on driver failure or parse failure
    so the calling workflow's andon engages."""
    try:
        import pexpect  # noqa: F401 — import check before threading
    except ImportError as e:
        raise ApplicationError(f"usage probe: pexpect missing ({e})",
                               non_retryable=True)
    raw = await asyncio.to_thread(_probe_blocking, timeout_s)
    parsed = _parse_usage(raw)
    parsed["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    parsed["parse_ok"] = True
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(parsed, indent=2) + "\n")
    return parsed
