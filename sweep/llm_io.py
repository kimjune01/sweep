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
            resp = await client.messages.create(
                model=model.model_id,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
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
        response_id = resp.id
    else:
        # Codex/Gemini wrappers TBD — fall back to a stub so the chain still
        # links and the attestation log records the *attempt*.
        duration_ms = 0
        response_text = f"<stub: {model.provider} wrapper not implemented>"
        input_tokens = 0
        output_tokens = 0
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
