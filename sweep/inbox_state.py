"""Inbox reading + state derivation.

The inbox layer is just JSONL files. This module knows the schema and the
three-way state split: queued / in_flight / done, derived from the actor
inbox plus _started.jsonl and _acks.jsonl sibling files.
"""

from __future__ import annotations

import json
from pathlib import Path


INBOX_DIR = Path.home() / ".sweep" / "inbox"


def load_msg_id_set(path: Path) -> set[str]:
    out: set[str] = set()
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            a = json.loads(line)
            if a.get("msg_id"):
                out.add(a["msg_id"])
        except json.JSONDecodeError:
            pass
    return out


def read_inbox(actor: str) -> tuple[list[dict], set[str]]:
    """Return (unacked messages, acked_msg_ids).

    Kept for backward compatibility and simple inspectors that don't care
    about the started/in-flight distinction.
    """
    inbox = INBOX_DIR / f"{actor}.jsonl"
    if not inbox.exists():
        return [], set()
    seen: dict[str, dict] = {}
    for line in inbox.read_text().splitlines():
        if not line.strip():
            continue
        try:
            m = json.loads(line)
            if m.get("msg_id"):
                seen[m["msg_id"]] = m
        except json.JSONDecodeError:
            pass

    acked = load_msg_id_set(INBOX_DIR / "_acks.jsonl")
    return [m for mid, m in seen.items() if mid not in acked], acked


def inbox_states(actor: str) -> dict[str, list[dict]]:
    """Partition an inbox into {'queued', 'in_flight', 'done'}.

    queued    = msg present, no start record
    in_flight = msg present, start record but no ack
    done      = msg present, ack record (regardless of start)
    """
    inbox = INBOX_DIR / f"{actor}.jsonl"
    seen: dict[str, dict] = {}
    if inbox.exists():
        for line in inbox.read_text().splitlines():
            if not line.strip():
                continue
            try:
                m = json.loads(line)
                if m.get("msg_id"):
                    seen[m["msg_id"]] = m
            except json.JSONDecodeError:
                pass

    started = load_msg_id_set(INBOX_DIR / "_started.jsonl")
    acked = load_msg_id_set(INBOX_DIR / "_acks.jsonl")

    states: dict[str, list[dict]] = {"queued": [], "in_flight": [], "done": []}
    for mid, m in seen.items():
        if mid in acked:
            states["done"].append(m)
        elif mid in started:
            states["in_flight"].append(m)
        else:
            states["queued"].append(m)
    return states
