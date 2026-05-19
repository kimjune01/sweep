"""Centralized claude-CLI subprocess plumbing.

Every place that spawns `claude` (or `pexpect.spawn("claude", ...)`)
must use this module so the OAuth/Max-plan routing and the env-pop
discipline can't be forgotten at a new call site.

See feedback_claude_cli_prefers_api_key memory for the root incident:
ANTHROPIC_API_KEY in the inherited shell env caused every substrate
claude call to bill API credits instead of Max plan, producing
multi-$100/day auto-recharges. Discovered 2026-05-18 during a
billing gemba. The fix is mechanical (pop the env var per spawn);
the durable fix is this module so the discipline lives in one place.
"""

from __future__ import annotations

import os


def env_without_api_key() -> dict:
    """Return a copy of os.environ with ANTHROPIC_API_KEY removed.

    Pass to subprocess.run(..., env=...) or pexpect.spawn(..., env=...).
    Without this, claude CLI prefers the API key over OAuth when both
    are available and bills the API credit balance.

    Codex unaffected; its auth path is independent (OPENAI_API_KEY or
    its own session). Same for any future provider's keys we add."""
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    return env
