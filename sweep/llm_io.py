"""LLM call wrapper. Every Anthropic/OpenAI/Google call should go through here.

Pipeline:
  1. Compute content hash of (model + params + prompt).
  2. Look up in attestations DB. If hit, return cached (zero tokens).
  3. Otherwise call provider, record both sides + hash-chain link, return.

Defense in depth: the wrapper is the only thing that writes to the
attestation log. Activities call the wrapper; they don't talk to provider
SDKs directly. That keeps the writer/reader split clean.
"""

from __future__ import annotations

import time

from sweep import attestations
from sweep.models import ModelInfo


def _strip_codex_envelope(raw: str) -> str:
    """Extract the assistant response from `codex exec -` output.

    Codex emits a transcript: a header (session id + separator), the
    `user` block, a `codex` block with the response, then a `tokens used`
    footer. We want just the codex block. Falling back to the raw output
    if the markers aren't present keeps the call returning *something*
    rather than empty on a CLI format change."""
    if "codex" not in raw or "tokens used" not in raw:
        return raw.strip()
    # Split on the literal `codex\n` line marking the response section;
    # take everything up to the `tokens used` footer.
    parts = raw.split("\ncodex\n", 1)
    if len(parts) < 2:
        return raw.strip()
    body = parts[1]
    body = body.split("\ntokens used\n", 1)[0]
    return body.strip()


async def call(
    model: ModelInfo,
    system: str,
    user: str,
    *,
    msg_id: str | None = None,
    repo: str | None = None,
    pr: int | None = None,
    max_tokens: int = 1024,
    temperature: float = 0.0,
    cache_system: bool = False,
) -> attestations.CallResult:
    """Make one LLM call (cache-first), record it, return the response.

    `msg_id`/`repo`/`pr` are provenance fields — they tag the call so retro
    can filter "all attestations from this workflow."
    """
    params = {"max_tokens": max_tokens, "temperature": temperature}
    key = attestations.compute_key(model.model_id, params, system, user)

    # Cache path — zero tokens.
    cached = attestations.lookup_by_key(key)
    if cached is not None:
        return attestations.CallResult(
            key=cached.key,
            response=cached.response,
            response_id=cached.response_id,
            input_tokens=cached.input_tokens,
            output_tokens=cached.output_tokens,
            duration_ms=cached.duration_ms,
            cached=True,
        )

    # Miss — call the provider.
    if model.provider == "anthropic":
        # Route via `claude -p` subprocess so the call bills against
        # the operator's Max plan (OAuth auth) instead of the API
        # credit balance. Cost was the driver: pre-swap, sift's hot
        # path alone burned ~$90/day in cache_creation tokens against
        # API credits; qa's opus adversary slot multiplied it.
        #
        # Trade-offs accepted:
        #   - ~1-2s subprocess overhead per call (no SDK, no streaming)
        #   - Ephemeral prompt cache is dropped (cache_system silently
        #     ignored); CLI doesn't expose per-call cache_control
        #   - Token counts not surfaced in print mode → set to 0,
        #     wasteboard's $$ panel will under-report Anthropic spend
        #     (acceptable: real spend is now Max-plan quota, not $$).
        #   - --bare would skip CLAUDE.md / hooks but forces
        #     ANTHROPIC_API_KEY back on, re-engaging the credit
        #     balance and defeating the routing. So no --bare;
        #     accept the context-load overhead.
        import asyncio as _asyncio
        import os as _os
        import subprocess as _subprocess
        from sweep.claude_subprocess import env_without_api_key
        env = env_without_api_key()  # OAuth → Max plan
        t0 = time.time()
        try:
            proc = await _asyncio.to_thread(
                _subprocess.run,
                ["claude", "-p",
                 "--model", model.model_id,
                 "--append-system-prompt", system,
                 user],
                capture_output=True, text=True, timeout=300, env=env,
            )
        except FileNotFoundError as e:
            from sweep import observe
            observe.event("llm_error", msg_id=msg_id, repo=repo, pr=pr,
                          model=model.model_id, provider="anthropic",
                          error_type="FileNotFoundError",
                          error_message=f"claude CLI not on PATH ({e})")
            observe.incr(f"llm_error:{model.provider}")
            raise
        except _subprocess.TimeoutExpired as e:
            from sweep import observe
            observe.event("llm_error", msg_id=msg_id, repo=repo, pr=pr,
                          model=model.model_id, provider="anthropic",
                          error_type="TimeoutExpired",
                          error_message="claude -p exceeded 300s")
            observe.incr(f"llm_error:{model.provider}")
            raise RuntimeError("claude -p timed out") from e
        duration_ms = int((time.time() - t0) * 1000)
        if proc.returncode != 0:
            from sweep import observe
            observe.event("llm_error", msg_id=msg_id, repo=repo, pr=pr,
                          model=model.model_id, provider="anthropic",
                          error_type="NonZeroExit",
                          error_message=(proc.stderr or proc.stdout or "")[:400])
            observe.incr(f"llm_error:{model.provider}")
            raise RuntimeError(
                f"claude -p rc={proc.returncode}: "
                f"{(proc.stderr or proc.stdout or '')[:200]}"
            )
        response_text = (proc.stdout or "").strip()
        input_tokens = 0
        output_tokens = 0
        cache_creation_tokens = 0
        cache_read_tokens = 0
        response_id = None
    elif model.provider == "openai":
        # Codex via CLI. The OpenAI SDK path would require a separate
        # API key and billing channel; shelling to `codex exec -` rides
        # the operator's existing Codex subscription instead. Token
        # counts aren't exposed by the CLI, so we leave them 0 — the
        # wasteboard's "API cost" panel only sums Anthropic providers
        # anyway, so undercounting OpenAI doesn't move the $$ display.
        import asyncio as _asyncio
        import subprocess as _subprocess
        combined = f"{system}\n\n---\n\n{user}"
        t0 = time.time()
        try:
            proc = await _asyncio.to_thread(
                _subprocess.run,
                ["codex", "exec", "-"],
                input=combined, capture_output=True, text=True,
                timeout=180,
            )
        except FileNotFoundError as e:
            from sweep import observe
            observe.event("llm_error", msg_id=msg_id, repo=repo, pr=pr,
                          model=model.model_id, provider="openai",
                          error_type="FileNotFoundError",
                          error_message=f"codex CLI not on PATH ({e})")
            raise
        except _subprocess.TimeoutExpired as e:
            from sweep import observe
            observe.event("llm_error", msg_id=msg_id, repo=repo, pr=pr,
                          model=model.model_id, provider="openai",
                          error_type="TimeoutExpired",
                          error_message="codex exec exceeded 180s")
            raise RuntimeError("codex exec timed out") from e
        duration_ms = int((time.time() - t0) * 1000)
        if proc.returncode != 0:
            from sweep import observe
            observe.event("llm_error", msg_id=msg_id, repo=repo, pr=pr,
                          model=model.model_id, provider="openai",
                          error_type="NonZeroExit",
                          error_message=(proc.stderr or proc.stdout or "")[:400])
            raise RuntimeError(
                f"codex exec rc={proc.returncode}: "
                f"{(proc.stderr or proc.stdout or '')[:200]}"
            )
        response_text = _strip_codex_envelope(proc.stdout or "")
        input_tokens = 0
        output_tokens = 0
        cache_creation_tokens = 0
        cache_read_tokens = 0
        response_id = None
    else:
        # Gemini wrapper TBD — fall back to a stub so the chain still
        # links and the attestation log records the *attempt*.
        duration_ms = 0
        response_text = f"<stub: {model.provider} wrapper not implemented>"
        input_tokens = 0
        output_tokens = 0
        cache_creation_tokens = 0
        cache_read_tokens = 0
        response_id = None

    row = attestations.record_call(
        key=key,
        model_id=model.model_id,
        model_nick=model.nick,
        provider=model.provider,
        duration_ms=duration_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        msg_id=msg_id,
        repo=repo,
        pr=pr,
        prompt=f"SYSTEM: {system}\n\nUSER: {user}",
        response=response_text,
        response_id=response_id,
        cache_creation_input_tokens=cache_creation_tokens,
        cache_read_input_tokens=cache_read_tokens,
    )
    return attestations.CallResult(
        key=row.key,
        response=row.response,
        response_id=row.response_id,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        duration_ms=row.duration_ms,
        cached=False,
    )
