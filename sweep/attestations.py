"""Attestation log — SQLite with a hash chain. Cache slot in the parts-bin.

Every LLM call across the pipeline writes through here. Each row stores the
bytes (prompt + response) AND a chain_hash linking it to the previous row.
Tampering any past row breaks the chain forward — the property comes from
the parts-bin's Merkle tree indexing entry: "any mutation invalidates the
root."

  schema:
    calls.key         = sha256(model_id || params_json || system || user)
    calls.chain_hash  = sha256(prev_chain_hash || key || response || ts)
    indexes on (ts, msg_id, repo, model_id) for O(log n) lookup

Three jobs:
  1. cache:   lookup_by_key → zero-token hit
  2. record:  record_call writes the row + advances the chain
  3. verify:  verify_chain walks the table and checks tamper-evidence
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path


DB_PATH = Path.home() / ".sweep" / "attestations" / "llm.db"


@dataclass
class CallRow:
    key: str
    model_id: str
    model_nick: str
    provider: str
    ts: str
    duration_ms: int
    input_tokens: int
    output_tokens: int
    msg_id: str | None
    repo: str | None
    pr: int | None
    prompt: str
    response: str
    response_id: str | None
    chain_hash: str


@dataclass
class CallResult:
    key: str
    response: str
    response_id: str | None
    input_tokens: int
    output_tokens: int
    duration_ms: int
    cached: bool


# ------------------------------------------------------------ schema


_SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
    key            TEXT PRIMARY KEY,
    model_id       TEXT NOT NULL,
    model_nick     TEXT NOT NULL,
    provider       TEXT NOT NULL,
    ts             TEXT NOT NULL,
    duration_ms    INTEGER,
    input_tokens   INTEGER,
    output_tokens  INTEGER,
    msg_id         TEXT,
    repo           TEXT,
    pr             INTEGER,
    prompt         TEXT NOT NULL,
    response       TEXT NOT NULL,
    response_id    TEXT,
    chain_hash     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ts    ON calls(ts);
CREATE INDEX IF NOT EXISTS idx_msg   ON calls(msg_id);
CREATE INDEX IF NOT EXISTS idx_repo  ON calls(repo);
CREATE INDEX IF NOT EXISTS idx_model ON calls(model_id);
"""


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript(_SCHEMA)
    return conn


# ------------------------------------------------------------ key + chain


def compute_key(model_id: str, params: dict, system: str, user: str) -> str:
    """Content hash of the call's deterministic inputs."""
    canon = json.dumps(params, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(
        f"{model_id}|{canon}|{system}|{user}".encode()
    ).hexdigest()


def _last_chain_hash(conn: sqlite3.Connection) -> str:
    cur = conn.execute("SELECT chain_hash FROM calls ORDER BY rowid DESC LIMIT 1")
    row = cur.fetchone()
    return row[0] if row else ""


def _link(prev: str, key: str, response: str, ts: str) -> str:
    return hashlib.sha256(f"{prev}|{key}|{response}|{ts}".encode()).hexdigest()


# ------------------------------------------------------------ ops


def lookup_by_key(key: str) -> CallRow | None:
    with _conn() as conn:
        cur = conn.execute("SELECT * FROM calls WHERE key = ?", (key,))
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        return CallRow(**dict(zip(cols, row)))


def record_call(*, key: str, model_id: str, model_nick: str, provider: str,
                duration_ms: int, input_tokens: int, output_tokens: int,
                msg_id: str | None, repo: str | None, pr: int | None,
                prompt: str, response: str, response_id: str | None) -> CallRow:
    """Insert a new call row with chain_hash linked to the previous.

    Two concurrent record_call invocations (e.g. codex_review and
    gemini_review finishing simultaneously) under SQLite's DEFERRED
    isolation would both read the same prev chain_hash via SELECT, compute
    chain_hashes against the same prev, and the second insert leaves a
    forked chain that verify_chain reports as tampered.

    The fix: open a dedicated autocommit connection and wrap the read-
    link-insert in BEGIN IMMEDIATE. The IMMEDIATE write lock blocks any
    other writer from making it past the SELECT until we commit, so the
    second writer sees our new chain_hash as their prev.
    """
    ts = dt.datetime.now(dt.timezone.utc).isoformat()
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), isolation_level=None, timeout=10)
    try:
        conn.executescript(_SCHEMA)
        conn.execute("BEGIN IMMEDIATE")
        try:
            prev = _last_chain_hash(conn)
            chain_hash = _link(prev, key, response, ts)
            conn.execute(
                """INSERT INTO calls (
                    key, model_id, model_nick, provider, ts, duration_ms,
                    input_tokens, output_tokens, msg_id, repo, pr,
                    prompt, response, response_id, chain_hash
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (key, model_id, model_nick, provider, ts, duration_ms,
                 input_tokens, output_tokens, msg_id, repo, pr,
                 prompt, response, response_id, chain_hash),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()
    return CallRow(
        key=key, model_id=model_id, model_nick=model_nick, provider=provider,
        ts=ts, duration_ms=duration_ms, input_tokens=input_tokens,
        output_tokens=output_tokens, msg_id=msg_id, repo=repo, pr=pr,
        prompt=prompt, response=response, response_id=response_id,
        chain_hash=chain_hash,
    )


def verify_chain() -> tuple[bool, int, int | None]:
    """Walk the whole log in insertion order, recompute each chain_hash,
    check each against stored value.

    Returns (ok, rows_checked, first_broken_rowid_or_None).
    """
    with _conn() as conn:
        cur = conn.execute(
            "SELECT rowid, key, response, ts, chain_hash FROM calls ORDER BY rowid"
        )
        prev = ""
        count = 0
        for rowid, key, response, ts, chain_hash in cur:
            count += 1
            expected = _link(prev, key, response, ts)
            if expected != chain_hash:
                return False, count, rowid
            prev = chain_hash
    return True, count, None


# ------------------------------------------------------------ queries


def recent(limit: int = 20) -> list[CallRow]:
    with _conn() as conn:
        cur = conn.execute(
            "SELECT * FROM calls ORDER BY rowid DESC LIMIT ?", (limit,)
        )
        cols = [d[0] for d in cur.description]
        return [CallRow(**dict(zip(cols, row))) for row in cur]


def for_msg(msg_id: str) -> list[CallRow]:
    with _conn() as conn:
        cur = conn.execute(
            "SELECT * FROM calls WHERE msg_id = ? ORDER BY rowid", (msg_id,)
        )
        cols = [d[0] for d in cur.description]
        return [CallRow(**dict(zip(cols, row))) for row in cur]


def token_summary() -> dict:
    """Sum input/output tokens by model. For token-cost forensics."""
    with _conn() as conn:
        cur = conn.execute(
            """SELECT model_nick, COUNT(*) AS n,
                      SUM(input_tokens) AS in_tokens,
                      SUM(output_tokens) AS out_tokens
               FROM calls GROUP BY model_nick"""
        )
        return {
            model: {"calls": n, "input_tokens": ti or 0, "output_tokens": to or 0}
            for model, n, ti, to in cur
        }
