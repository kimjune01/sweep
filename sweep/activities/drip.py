"""Drip activity — one cycle of the /drip skill per message.

Each DripActor signal corresponds to a routed (repo, intent) pair:
ship, rebase, or close. The LLM-shaped work (tone-matching, codex
lineup, feedback ingestion) lives in skills/drip.md and is invoked
via `claude --print '/drip <repo>'`. The deterministic plumbing
(queue read, gh push, hard gates) is handled by the skill calling
back into `sweep drip` subcommands.

This activity is the bridge: receive a Message, shell out to claude
with the appropriate slash command, capture exit status, surface
failures as non-retryable ApplicationError so the actor's andon cord
catches them.
"""

from __future__ import annotations

import subprocess

from temporalio import activity
from temporalio.exceptions import ApplicationError

from sweep.types import Message


_INTENT_TO_FLAG = {
    "ship":   "--push",
    "rebase": "--push",   # rebase + force-push; the skill handles the safety
    "close":  "--check",  # close is a check-and-comment path, not a push
}


@activity.defn
async def drip_cycle(msg: Message) -> dict:
    """Invoke the /drip skill for one routed message.

    Returns a small dict with exit code, intent, repo, and a short
    stdout/stderr trailer. Halting failures become ApplicationError
    so QaActor-style andon engages.
    """
    if not msg.repo:
        raise ApplicationError("drip: repo required", non_retryable=True)
    intent = msg.intent or "ship"
    flag = _INTENT_TO_FLAG.get(intent, "--check")

    cmd = ["claude", "--print", f"/drip {msg.repo} {flag}"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except FileNotFoundError as e:
        raise ApplicationError(
            f"drip: claude not on PATH ({e})", non_retryable=True,
        )
    except subprocess.TimeoutExpired:
        raise ApplicationError(
            f"drip: /drip {msg.repo} exceeded 10min timeout",
            non_retryable=True,
        )

    if result.returncode != 0:
        raise ApplicationError(
            f"drip: /drip {msg.repo} {flag} failed (rc={result.returncode}): "
            f"{(result.stderr or '')[:400]}",
            non_retryable=True,
        )
    return {
        "repo": msg.repo,
        "intent": intent,
        "flag": flag,
        "rc": result.returncode,
        "stdout_tail": (result.stdout or "")[-400:],
    }
