#!/usr/bin/env python3
"""End-to-end test of llm_io + attestation log against real Haiku tokens.

Live in tests, not mocks. Variance is the point. Haiku is the test-fixture
model — high variance + cheap = exercises every error path frequently
without burning Opus/Sonnet spend.

What this proves:
  1. llm_io.call() actually hits the Anthropic API
  2. The response gets written to the attestation log
  3. A second identical call returns from cache, zero tokens, no chain advance
  4. A different prompt advances the chain
  5. verify_chain() walks the full log cleanly
  6. Tampering any past row breaks the chain forward

Run:
  ANTHROPIC_API_KEY=sk-… uv run python scripts/e2e-haiku.py

Idempotent: creates its own scratch DB at ~/.sweep/attestations/e2e-haiku.db
and cleans it up at the end. Won't touch your real attestation log.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
import time
from pathlib import Path

# Redirect the attestation DB to a scratch file BEFORE importing sweep modules
# so we don't touch ~/.sweep/attestations/llm.db.
SCRATCH_DB = Path.home() / ".sweep" / "attestations" / "e2e-haiku.db"
SCRATCH_DB.parent.mkdir(parents=True, exist_ok=True)
SCRATCH_DB.unlink(missing_ok=True)

import sweep.attestations as att  # noqa: E402

att.DB_PATH = SCRATCH_DB  # redirect

from sweep import llm_io  # noqa: E402
from sweep.models import resolve  # noqa: E402


# ---------- assertion helpers ----------


PASS = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"


def check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  {PASS} {label}{(' — ' + detail) if detail else ''}")
    else:
        print(f"  {FAIL} {label}{(' — ' + detail) if detail else ''}")
        sys.exit(1)


def stage(name: str) -> None:
    print()
    print(f"\033[1m▸ {name}\033[0m")


# ---------- the test ----------


async def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set — refusing to fake it.")
        return 1

    haiku = resolve("haiku")
    print(f"# scratch db: {SCRATCH_DB}")
    print(f"# model:      {haiku.nick} ({haiku.model_id})")

    # --- stage 1: cold cache, first call hits the wire ---
    stage("stage 1 — cold cache, first call")
    t0 = time.time()
    r1 = await llm_io.call(
        haiku,
        system="Respond with exactly one word, lowercase.",
        user="What color is a stop sign?",
        msg_id="e2e-1",
        repo="test/fixture",
        pr=1,
        max_tokens=20,
        temperature=0.0,
    )
    dt1 = time.time() - t0
    check("call returned a response", bool(r1.response.strip()), repr(r1.response[:60]))
    check("first call was not cached", r1.cached is False)
    check("provider returned a response_id", bool(r1.response_id))
    check("input_tokens > 0", r1.input_tokens > 0, f"{r1.input_tokens}")
    check("output_tokens > 0", r1.output_tokens > 0, f"{r1.output_tokens}")
    check("duration_ms > 0", r1.duration_ms > 0, f"{r1.duration_ms}ms")
    check("real network call took >100ms", dt1 > 0.1, f"{dt1*1000:.0f}ms")

    # --- stage 2: same call → cache hit, no tokens, no chain advance ---
    stage("stage 2 — identical call, cache hit")
    before_count = _row_count()
    t0 = time.time()
    r2 = await llm_io.call(
        haiku,
        system="Respond with exactly one word, lowercase.",
        user="What color is a stop sign?",
        msg_id="e2e-1-replay",
        repo="test/fixture",
        pr=1,
        max_tokens=20,
        temperature=0.0,
    )
    dt2 = time.time() - t0
    after_count = _row_count()
    check("second call returned same response bytes", r2.response == r1.response,
          repr(r2.response[:60]))
    check("second call was cached", r2.cached is True)
    check("no new row inserted (cache hit)", after_count == before_count,
          f"{before_count} → {after_count}")
    check("cache hit was fast (<50ms)", dt2 < 0.05, f"{dt2*1000:.0f}ms")

    # --- stage 3: different prompt → new call, chain advances ---
    stage("stage 3 — different prompt, chain advances")
    before_count = _row_count()
    r3 = await llm_io.call(
        haiku,
        system="Respond with exactly one word, lowercase.",
        user="What color is grass?",
        msg_id="e2e-2",
        repo="test/fixture",
        pr=2,
        max_tokens=20,
        temperature=0.0,
    )
    after_count = _row_count()
    check("new prompt was not cached", r3.cached is False)
    check("exactly one new row appended", after_count == before_count + 1,
          f"{before_count} → {after_count}")
    check("new row has different key", r3.key != r1.key)

    # --- stage 4: chain integrity ---
    stage("stage 4 — chain integrity")
    ok, count, broken = att.verify_chain()
    check("verify_chain() passes", ok, f"{count} rows checked")
    check("broken_rowid is None", broken is None)
    check("chain length is 2", count == 2, f"got {count}")

    # --- stage 5: tamper detection ---
    stage("stage 5 — tamper detection")
    conn = sqlite3.connect(str(SCRATCH_DB))
    conn.execute("UPDATE calls SET response = 'TAMPERED' WHERE rowid = 1")
    conn.commit()
    conn.close()
    ok, count, broken = att.verify_chain()
    check("verify_chain() detects tamper", ok is False)
    check("first broken row is rowid 1", broken == 1, f"got rowid {broken}")

    # --- stage 6: per-msg lookup ---
    stage("stage 6 — per-msg attestation lookup")
    # Reset (un-tamper for this read)
    conn = sqlite3.connect(str(SCRATCH_DB))
    conn.execute("UPDATE calls SET response = ? WHERE rowid = 1", (r1.response,))
    conn.commit()
    conn.close()
    e2e1 = att.for_msg("e2e-1")
    e2e2 = att.for_msg("e2e-2")
    check("e2e-1 has 1 attestation", len(e2e1) == 1, f"got {len(e2e1)}")
    check("e2e-2 has 1 attestation", len(e2e2) == 1, f"got {len(e2e2)}")

    # --- stage 7: token summary ---
    stage("stage 7 — token summary")
    summary = att.token_summary()
    check("haiku in summary", "haiku" in summary, repr(list(summary)))
    check("token totals nonzero",
          summary["haiku"]["input_tokens"] > 0 and summary["haiku"]["output_tokens"] > 0,
          f"in={summary['haiku']['input_tokens']} out={summary['haiku']['output_tokens']}")

    # --- cleanup ---
    SCRATCH_DB.unlink(missing_ok=True)
    print()
    print(f"\033[32mall stages passed.\033[0m  scratch db cleaned up.")
    return 0


def _row_count() -> int:
    conn = sqlite3.connect(str(SCRATCH_DB))
    n = conn.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
    conn.close()
    return n


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
