"""skill_result — universal contract for "what did this skill decide?"

Each LLM-shelling activity (drip_cycle, triage_cycle, investigate_cycle,
qa_cycle) ends with a `shim(skill_name, raw_stdout) -> dict` call that
takes the skill's free-form stdout and returns a guaranteed-schema dict.

Why a shim instead of trusting the skill: the skill is a free-form LLM
process; sometimes it forgets to emit JSON, emits malformed JSON, wraps
it in markdown, narrates around it, etc. The shim runs a tight
Sonnet-via-subscription pass that extracts the schema deterministically.
Same Claude subscription as the skills — no API tokens, no GitHub
budget hit, ~1 extra call per skill run.

The shim NEVER raises. On any failure (timeout, malformed JSON,
schema violation) it returns `{}` and lets the caller fall back to
its own heuristics. The activity wrapper still ack-and-records the
outcome event with whatever it learned — better partial than none.
"""

from __future__ import annotations

import json
from typing import Any

from sweep import llm_cli


# Universal fields present in every schema. A skill that cannot
# fulfill its job sets `rejected=true` with a reason; the wrapper
# routes the item to ~/.sweep/inbox/rejected.jsonl for operator
# review instead of ack-and-forgetting it. Rejection is the third
# outcome shape after "decided" and "errored" — distinct from both.
_UNIVERSAL = {
    "rejected":      "boolean — true if the skill could not fulfill this job (missing context, ambiguous repo, broken precondition). Distinct from 'decided no' (drop/no_fix/etc.) — rejection means 'don't ack me, route me'.",
    "reject_reason": "short string explaining the rejection, else null",
}

# Per-skill schemas. Keep field names stable — they become the keys
# in observability events (triage_decision, investigate_done, etc.)
# and bumping them is a downstream-breaking change.
SCHEMAS: dict[str, dict[str, str]] = {
    "triage": {
        "decision": "one of: drop, surface, investigate, defer",
        "score":    "integer 0-10 (priority/quality, 10 = highest)",
        "reason":   "short string, why this decision",
        **_UNIVERSAL,
    },
    "investigate": {
        "produced_pr": "boolean — did the investigation result in an opened PR or pushed branch?",
        "pr_url":      "string URL of the PR if opened, else null",
        "no_fix":      "boolean — did the investigation conclude 'no fix possible/worth-shipping'?",
        "summary":     "short string — one-sentence outcome summary",
        **_UNIVERSAL,
    },
    "drip": {
        "pushed":  "boolean — did /drip actually push commits or open a PR this run?",
        "pr_url":  "string URL of the PR touched, else null",
        "outcome": "one of: pushed, rebased, checked, noop, failed",
        "reason":  "short string, what happened",
        **_UNIVERSAL,
    },
    "qa": {
        "verdict":      "one of: pass, fail, needs_human",
        "issues_found": "array of short strings; empty when verdict=pass",
        "reason":       "short string, one-sentence summary",
        **_UNIVERSAL,
    },
}


def is_rejected(parsed: dict) -> bool:
    """Did the skill explicitly decline this job?"""
    return bool(parsed.get("rejected"))


def record_rejection(skill_name: str, msg: dict, parsed: dict) -> None:
    """Route a rejected job to the rejected inbox + emit an event so
    leakdog can surface it. The original msg is preserved for the
    operator to re-route or amend."""
    import datetime as _dt
    import json as _json
    from pathlib import Path
    from sweep import observe

    inbox = Path.home() / ".sweep" / "inbox" / "rejected.jsonl"
    inbox.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts":     _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "skill":  skill_name,
        "reason": parsed.get("reject_reason") or "(no reason given)",
        "msg":    msg,
    }
    try:
        with open(inbox, "a") as f:
            f.write(_json.dumps(entry, default=str) + "\n")
    except OSError:
        pass
    observe.event(
        f"{skill_name}_rejected",
        repo=(msg.get("repo") if isinstance(msg, dict) else None),
        pr=(msg.get("pr") if isinstance(msg, dict) else None),
        reason=parsed.get("reject_reason") or "",
    )


# Default model: subscription Sonnet is cheap for shaping. Operator
# can override per-call if a different size is needed (e.g. fall back
# to haiku if subscription is hot).
DEFAULT_SHIM_MODEL = "sonnet"

# Tight timeout: the shim should be fast. A schema-extraction prompt
# rarely needs more than a few seconds. If it times out, fall back
# to heuristics — better than blocking the activity for 2 minutes.
SHIM_TIMEOUT_S = 30


def shim(skill_name: str, raw_stdout: str, *,
         model: str = DEFAULT_SHIM_MODEL) -> dict[str, Any]:
    """Extract the schema for `skill_name` from `raw_stdout`. Returns
    `{}` on any failure — callers should treat the empty dict as
    "shim couldn't help, use heuristics" rather than as a decision."""
    schema = SCHEMAS.get(skill_name)
    if not schema or not raw_stdout.strip():
        return {}
    system = _build_prompt(skill_name, schema)
    try:
        out = llm_cli.call(system, raw_stdout,
                           model=model, timeout_s=SHIM_TIMEOUT_S)
    except Exception:
        return {}
    return _parse_json(out)


def _build_prompt(skill_name: str, schema: dict[str, str]) -> str:
    fields = "\n".join(f'  "{k}": {v}' for k, v in schema.items())
    return (
        f"You are extracting structured fields from the output of the "
        f"{skill_name!r} skill.\n\n"
        f"Schema (return ONE JSON object with exactly these keys):\n"
        f"{{\n{fields}\n}}\n\n"
        f"Rules:\n"
        f"- Return ONLY the JSON object. No prose, no markdown fences.\n"
        f"- If a field cannot be determined from the text, use null.\n"
        f"- For boolean fields, prefer true/false over null when there's "
        f"any signal in the text.\n"
        f"- Keep string fields under 200 characters."
    )


def _parse_json(raw: str) -> dict[str, Any]:
    """Best-effort JSON parse. Strips markdown fences and prose."""
    text = raw.strip()
    # Strip ```json ... ``` fences if present
    if text.startswith("```"):
        # Drop the opening fence + optional language tag
        first_newline = text.find("\n")
        if first_newline > 0:
            text = text[first_newline + 1:]
        # Drop the closing fence
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    # If the model wrapped JSON in prose, find the outermost { ... }
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end + 1]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
