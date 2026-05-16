"""Claude CLI as the default LLM channel for unstructured text answers.

Principle: `claude --print` for everything; API only when we need JSON
schema enforcement, prompt-cache for hot paths, or per-call attestation.
The CLI runs on subscription — zero per-call billing — and one billing
rail means one place to monitor consumption (the /usage probe).

`call(system, user)` returns the model's stdout text. Empty stdout
raises ApplicationError: an empty response is never a valid answer
and almost always means auth / rate / binary failure. Pulling the
andon cord on empty is the correct failure shape, not a silent "".
"""

from __future__ import annotations

import subprocess

from temporalio.exceptions import ApplicationError


def call(system: str, user: str, *, timeout_s: int = 120) -> str:
    """One claude --print invocation. Combines system + user into a
    single prompt (the CLI's print mode is single-message). Returns
    trimmed stdout. Raises ApplicationError on missing binary,
    timeout, non-zero exit, or empty stdout — all of which are
    structural failures the caller's actor should andon on, not
    treat as a non-answer."""
    if not user.strip():
        raise ApplicationError("llm_cli: empty user prompt",
                               non_retryable=True)
    prompt = f"{system.strip()}\n\n---\n\n{user.strip()}" if system.strip() else user
    try:
        result = subprocess.run(
            ["claude", "--print", prompt],
            capture_output=True, text=True, timeout=timeout_s,
        )
    except FileNotFoundError as e:
        raise ApplicationError(f"llm_cli: claude not on PATH ({e})",
                               non_retryable=True)
    except subprocess.TimeoutExpired:
        raise ApplicationError(f"llm_cli: claude exceeded {timeout_s}s",
                               non_retryable=True)
    if result.returncode != 0:
        raise ApplicationError(
            f"llm_cli: claude rc={result.returncode}: "
            f"{(result.stderr or '')[:300]}",
            non_retryable=True,
        )
    out = (result.stdout or "").strip()
    if not out:
        raise ApplicationError(
            "llm_cli: claude returned empty stdout (auth/rate/binary?)",
            non_retryable=True,
        )
    return out
