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

import os
import subprocess

from temporalio.exceptions import ApplicationError


def call(system: str, user: str, *, timeout_s: int = 120,
         model: str | None = None, allow_empty: bool = False) -> str:
    """One claude --print invocation. Combines system + user into a
    single prompt (the CLI's print mode is single-message). Returns
    trimmed stdout. Raises ApplicationError on missing binary,
    timeout, or non-zero exit.

    Empty stdout: by default treated as a structural failure (auth /
    rate / binary). Pass `allow_empty=True` when the prompt's contract
    explicitly permits an empty answer (e.g. infer_test_cmd says
    "empty is a legal answer if the repo has no tests / convention is
    unclear"). With `allow_empty=True`, returns "" instead of raising.

    `model` overrides the default; pass 'sonnet' for cheap shaping
    tasks like skill_result.shim where Opus would be overkill.

    Pops ANTHROPIC_API_KEY from the subprocess env so claude uses
    OAuth/Max plan instead of API credits — same fix applied to
    skill_runner, comment-issue, file-issue, switch. The inherited
    env var was the silent root of multi-$100/day burn discovered
    2026-05-18; see feedback_claude_cli_prefers_api_key."""
    if not user.strip():
        raise ApplicationError("llm_cli: empty user prompt",
                               non_retryable=True)
    prompt = f"{system.strip()}\n\n---\n\n{user.strip()}" if system.strip() else user
    cmd = ["claude", "--print"]
    if model:
        cmd += ["--model", model]
    cmd.append(prompt)
    from sweep.claude_subprocess import env_without_api_key as _env_no_key
    env = _env_no_key()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=timeout_s, env=env,
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
    if not out and not allow_empty:
        raise ApplicationError(
            "llm_cli: claude returned empty stdout (auth/rate/binary?)",
            non_retryable=True,
        )
    return out
