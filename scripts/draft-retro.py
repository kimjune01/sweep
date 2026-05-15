#!/usr/bin/env python3
"""Drive haiku end-to-end through the retro pipeline.

  events.jsonl + counters.db
        ↓
  build a structured prompt
        ↓
  llm_io.call(haiku) → SOAP-shaped response
        ↓
  parse → four section strings
        ↓
  shell out to `sweep retro record --subjective ... --plan ...`

This is the path the /retro skill will take, just without the skill
markdown wrapper. Useful for sanity-checking the loop with a cheap
high-variance model before any production retro fires.

Run:
  ANTHROPIC_API_KEY=sk-… uv run python scripts/draft-retro.py
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys

from sweep import llm_io, observe
from sweep.models import resolve


SYSTEM = """\
You are filling in a SOAP one-pager that summarizes one cycle of a
PR-pipeline's forward pass. Four sections:

  S — Subjective: what the actors emitted (paraphrase event payloads)
  O — Objective: what the counters and event-derivations show
  A — Assessment: diagnosis, naming codebase components by name
                  (qa cascade, prospect labels, gh_io cache, observe, etc.)
  P — Plan: concrete commits to make, or "(none)" if nothing actionable

Constraints:
  - Each section is a markdown bullet list, 2–5 bullets, terse.
  - The A section names files/components, not abstract roles.
  - The P section is empty if the cycle was quiet; do not invent work.
  - No preamble, no closing remarks, no markdown headers — only the
    four sections delimited as `=== S ===`, `=== O ===`, `=== A ===`,
    `=== P ===`. Anything else and the downstream parser fails.
"""


def build_user_prompt(events: list[dict], counters: dict[str, int]) -> str:
    return f"""\
Events (most recent first, JSON Lines):
{chr(10).join(json.dumps(e) for e in events) or "(none)"}

Counters (aggregate over the window):
{chr(10).join(f"  {k}: {v}" for k, v in sorted(counters.items())) or "(none)"}

Render the four SOAP sections delimited by `=== S ===` style markers.
"""


SECTION_RE = re.compile(
    r"===\s*S\s*===\s*\n(?P<s>.*?)\n===\s*O\s*===\s*\n(?P<o>.*?)\n"
    r"===\s*A\s*===\s*\n(?P<a>.*?)\n===\s*P\s*===\s*\n(?P<p>.*)",
    re.DOTALL,
)


def parse_response(response: str) -> dict[str, str]:
    m = SECTION_RE.search(response)
    if not m:
        print(f"PARSE FAIL — raw response below:\n{response}", file=sys.stderr)
        sys.exit(1)
    return {
        "subjective": m.group("s").strip(),
        "objective": m.group("o").strip(),
        "assessment": m.group("a").strip(),
        "plan": m.group("p").strip() or "(none)",
    }


async def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set", file=sys.stderr)
        return 1

    events = observe.events_recent(limit=50)
    counters = observe.counters_all()

    if not events and not counters:
        print("# no events or counters — nothing to fold")
        return 0

    haiku = resolve("haiku")
    user = build_user_prompt(events, counters)
    print(f"# folding {len(events)} events, {len(counters)} counters via {haiku.nick}",
          file=sys.stderr)

    result = await llm_io.call(
        haiku,
        system=SYSTEM,
        user=user,
        max_tokens=600,
        temperature=0.0,
    )
    sections = parse_response(result.response)

    cmd = [
        "uv", "run", "sweep", "retro", "record",
        "--subjective", sections["subjective"],
        "--objective", sections["objective"],
        "--assessment", sections["assessment"],
        "--plan", sections["plan"],
    ]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        print(f"sweep retro record failed (rc={out.returncode}):\n"
              f"stdout: {out.stdout}\nstderr: {out.stderr}", file=sys.stderr)
        return 1
    print(out.stdout, end="")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
