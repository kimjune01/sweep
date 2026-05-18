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


# ── Cross-actor station derivation ──────────────────────────────────
#
# A given (repo, pr) can appear in N actor inboxes — qa.jsonl carries
# the bulk-backfill kick AND retro_audit.jsonl carries the older "wait"
# classification from notification_poller. Reading those independently
# (the previous lanes view) double-counted: 67 qa + 113 in-flight ≠ 113
# unique PRs in flight. The Toyota property says one card, one column.
#
# `current_station(repo, pr, pipeline)` returns the rightmost pipeline
# station holding the (repo, pr) pair in non-done state. Views consult
# this once; columns become genuinely exclusive at render time.


def current_station(
    repo: str,
    pr: int | None,
    pipeline: list[tuple[str, str]],
) -> str | None:
    """For (repo, pr), return the label of the rightmost station in
    `pipeline` that holds it in queued or in_flight. None if the pair
    isn't currently tracked anywhere.

    `pipeline` is the ordered list of `(actor_name, label)` left→right.
    Walking right→left, the first hit wins — that's the "furthest
    along" position. The card's done-state in earlier stations doesn't
    pull it backwards; only active (queued / in_flight) presence in a
    later station moves it rightward.
    """
    if not repo or pr is None:
        return None
    for actor, label in reversed(pipeline):
        s = inbox_states(actor)
        for m in s.get("queued", []) + s.get("in_flight", []):
            if m.get("repo") == repo and m.get("pr") == pr:
                return label
    return None


def lane_assignments(
    pipeline: list[tuple[str, str]],
) -> dict[str, list[dict]]:
    """Single-pass partition: every (repo, pr) currently in any tracked
    inbox is assigned to exactly one station — the one whose inbox holds
    the freshest entry for that pair. Returns `{label: [msg, ...]}`.

    Rule is **most-recently-touched wins**, not rightmost-by-position.
    Rightmost-by-position fails because the pipeline column order in
    views (qa → respond → in flight → human) doesn't always reflect
    actual workflow precedence — `retro_audit` ("in flight" in the
    lanes view) is a passive observation surface that catches every
    PR remit ever classified as `wait`. With rightmost-by-position it
    would always claim PRs that are right-now active in qa, because
    its column is further right. With most-recently-touched, the qa
    kick supersedes the older wait classification — the card sits in
    qa as long as that's where the freshest activity is.

    Position-order remains the tiebreaker when two stations have
    identical timestamps for the same pair (vanishingly rare; same-ms
    deposits from a single bulk run). Rightmost wins the tie.
    """
    # Pre-load every actor's queued + in_flight, dedup within-actor.
    actor_msgs: dict[str, list[dict]] = {}
    for actor, _label in pipeline:
        s = inbox_states(actor)
        by_key: dict[tuple, dict] = {}
        for m in sorted(
            s.get("queued", []) + s.get("in_flight", []),
            key=lambda x: x.get("ts", ""),
        ):
            key = (m.get("repo"), m.get("pr"))
            by_key[key] = m
        actor_msgs[actor] = list(by_key.values())

    # Build (pair → best station label) by walking each actor's entries
    # and keeping the one with the freshest timestamp (rightmost label
    # wins on tie). Position index from the pipeline list provides the
    # tiebreaker.
    label_for_actor = {actor: label for actor, label in pipeline}
    position = {actor: i for i, (actor, _) in enumerate(pipeline)}
    best: dict[tuple, tuple[str, str, int]] = {}
    # value: (ts, label, position)
    for actor, msgs in actor_msgs.items():
        label = label_for_actor[actor]
        pos = position[actor]
        for m in msgs:
            pair = (m.get("repo"), m.get("pr"))
            ts = m.get("ts", "")
            prev = best.get(pair)
            # Strict-greater on ts; on equal ts, prefer larger position
            # (rightmost) — this is the rare tiebreaker that preserves
            # the original "advanced-station wins" intuition.
            if (prev is None
                    or ts > prev[0]
                    or (ts == prev[0] and pos > prev[2])):
                best[pair] = (ts, label, pos)

    # Re-bucket the actor messages into their winning station's column.
    columns: dict[str, list[dict]] = {label: [] for _, label in pipeline}
    for actor, msgs in actor_msgs.items():
        label = label_for_actor[actor]
        for m in msgs:
            pair = (m.get("repo"), m.get("pr"))
            won = best.get(pair)
            if won and won[1] == label:
                columns[label].append(m)
    for label in columns:
        columns[label].sort(key=lambda x: x.get("ts", ""))
    return columns
