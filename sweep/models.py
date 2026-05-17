"""Model registry, nicknames, role defaults, adversarial cascade.

Skills and activities ask for models by nickname (opus, sonnet, haiku, codex,
gemini, flash). This module resolves nicknames to provider + model id, picks
a default per role, and defines the adversarial review cascade.

The discipline: code never hard-codes a model ID. It calls resolve("sonnet")
or default_for("orchestrate"). Switching models means one edit here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

# ---------------------------------------------------------------- nicknames

Nick = Literal["opus", "sonnet", "haiku", "codex", "gemini", "flash"]


@dataclass(frozen=True)
class ModelInfo:
    nick: str
    provider: str  # "anthropic" | "openai" | "google"
    model_id: str
    note: str = ""


REGISTRY: dict[str, ModelInfo] = {
    # Anthropic
    "opus":   ModelInfo("opus",   "anthropic", "claude-opus-4-7",
                        "judgment-heavy: orchestration, coding, adversarial fallback"),
    "sonnet": ModelInfo("sonnet", "anthropic", "claude-sonnet-4-6",
                        "default for work-shuffling: pr-state, classify, route"),
    "haiku":  ModelInfo("haiku",  "anthropic", "claude-haiku-4-5-20251001",
                        "test scaffolding only — high variance is the point"),
    # OpenAI
    "codex":  ModelInfo("codex",  "openai",    "gpt-5.5-codex",
                        "first adversary in cascade — structural reasoning"),
    # Google
    "gemini": ModelInfo("gemini", "google",    "gemini-3.1-pro-preview",
                        "second adversary in cascade — logic tracing"),
    "flash":  ModelInfo("flash",  "google",    "gemini-flash-3.1",
                        "cheap variant — bulk Google calls without Pro spend"),
}


def resolve(nick: str) -> ModelInfo:
    if nick not in REGISTRY:
        raise ValueError(
            f"unknown model nickname {nick!r}; pick one of "
            f"{sorted(REGISTRY)}"
        )
    return REGISTRY[nick]


# ---------------------------------------------------------------- roles

Role = Literal[
    "orchestrate",          # shuffling work, picking entries, classifying
    "code",                 # general coding tasks — write fixes, implement
    "investigate_primary",  # primary hypothesis generator (the calling agent)
    "investigate_pushout",  # second hypothesis generator for blind-blind-merge
    "adversary_1",          # first reviewer in the cascade
    "adversary_2",          # second reviewer
    "adversary_3",          # fallback reviewer
]

# Per-role defaults. Override via env var SWEEP_MODEL_<role>=<nick>.
ROLE_DEFAULTS: dict[str, str] = {
    "orchestrate":          "sonnet",
    "code":                 "opus",
    # Blind-blind-merge at investigate: two hypothesis generators run
    # blind to each other; the merge step extracts DISAGREEMENTS more
    # than agreements — consensus is low-entropy (training overlap),
    # divergence is where the real signal hides. Default secondary is
    # sonnet (cheap, complementary failure modes to opus). Swap to
    # codex/gemini via SWEEP_MODEL_INVESTIGATE_PUSHOUT for more
    # entropy when acceptance rate justifies the cost.
    "investigate_primary":  "opus",
    "investigate_pushout":  "sonnet",
    "adversary_1":          "codex",
    "adversary_2":          "gemini",
    "adversary_3":          "opus",
}


def default_for(role: str) -> ModelInfo:
    """Pick the model for a role. Env-var override: SWEEP_MODEL_<role>=<nick>."""
    env = os.environ.get(f"SWEEP_MODEL_{role.upper()}")
    nick = env or ROLE_DEFAULTS.get(role)
    if not nick:
        raise ValueError(f"no default for role {role!r}")
    return resolve(nick)


# ---------------------------------------------------------------- cascade


def adversary_cascade() -> list[ModelInfo]:
    """Iterative-review cascade. Tries adversary_1, then _2, then _3.

    A reviewer that returns a credit/quota error advances the cascade. A
    reviewer that returns a verdict (pass/fail/revise) wins — no further
    reviewers tried for that round.

    Default order: codex → gemini → opus subagent. Override per slot via
    SWEEP_MODEL_ADVERSARY_1 / _2 / _3.
    """
    return [
        default_for("adversary_1"),
        default_for("adversary_2"),
        default_for("adversary_3"),
    ]


# ---------------------------------------------------------------- utilities


def describe() -> str:
    """Human-readable summary — useful for `sweep models` introspection."""
    lines = ["Model registry:"]
    for nick, info in REGISTRY.items():
        lines.append(f"  {nick:7s} {info.provider:10s} {info.model_id}  — {info.note}")
    lines.append("\nRole defaults:")
    for role, nick in ROLE_DEFAULTS.items():
        env_key = f"SWEEP_MODEL_{role.upper()}"
        override = os.environ.get(env_key)
        actual = override or nick
        suffix = f"  (overridden via {env_key})" if override else ""
        lines.append(f"  {role:13s} → {actual}{suffix}")
    lines.append("\nAdversary cascade: " + " → ".join(
        m.nick for m in adversary_cascade()
    ))
    return "\n".join(lines)
