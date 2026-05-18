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
        import anthropic
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic()
        t0 = time.time()
        try:
            # Anthropic prompt cache: when `cache_system=True`, mark
            # the system prompt as ephemeral so the API caches the
            # prefix for ~5min. Subsequent calls with the same system
            # within the window pay ~10% of the input-token cost.
            # Worth it for hot paths (sift's should_triage_issue
            # ticks every few minutes with a stable system).
            sys_arg: object = (
                [{"type": "text", "text": system,
                  "cache_control": {"type": "ephemeral"}}]
                if cache_system else system
            )
            resp = await client.messages.create(
                model=model.model_id,
                max_tokens=max_tokens,
                temperature=temperature,
                system=sys_arg,
                messages=[{"role": "user", "content": user}],
            )
        except anthropic.APIError as e:
            # Capture the failure as an observe event (with the call's
            # provenance and the error class/message) but do NOT write a
            # row to the attestation log. Writing under the success key
            # would poison the cache: the next retry would find an error
            # string instead of hitting the wire, and the verdict parser
            # would treat it as a reviewer opinion ("revise"). The chain
            # is allowed to have no row for a failed attempt; retro reads
            # the observe event to know it happened.
            from sweep import observe
            observe.event(
                "llm_error",
                msg_id=msg_id,
                repo=repo,
                pr=pr,
                model=model.model_id,
                provider=model.provider,
                error_type=type(e).__name__,
                error_message=str(e)[:500],
                duration_ms=int((time.time() - t0) * 1000),
            )
            observe.incr(f"llm_error:{model.provider}")
            raise
        duration_ms = int((time.time() - t0) * 1000)
        response_text = "".join(
            block.text for block in resp.content if hasattr(block, "text")
        )
        input_tokens = resp.usage.input_tokens
        output_tokens = resp.usage.output_tokens
        # Anthropic's usage object reports cache_creation and cache_read
        # as separate fields; neither is included in input_tokens. Cache
        # creation is billed at 1.25× input rate, reads at 0.1×. Without
        # capturing these the wasteboard severely undercounts spend
        # whenever cache_system=True is used — sift's hot path was the
        # witness, ~$90/day in cache_creation that didn't show on the
        # wasteboard at all. getattr with default 0 keeps the wrapper
        # backward-compatible with SDK versions that don't report them.
        cache_creation_tokens = getattr(
            resp.usage, "cache_creation_input_tokens", 0) or 0
        cache_read_tokens = getattr(
            resp.usage, "cache_read_input_tokens", 0) or 0
        response_id = resp.id
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
