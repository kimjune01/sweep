"""`sweep inbox <actor>` — inspect one mailbox, dedupe by msg_id."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from sweep.inbox_state import INBOX_DIR, load_msg_id_set


inbox_app = typer.Typer(
    help="Inspect one actor inbox",
    no_args_is_help=True,
    invoke_without_command=True,
)


def _inspect(actor: str) -> None:
    inbox = INBOX_DIR / f"{actor}.jsonl"
    if not inbox.exists():
        print(f"# {inbox} — no messages")
        return

    seen: dict[str, dict] = {}
    raw = 0
    for line in inbox.read_text().splitlines():
        if not line.strip():
            continue
        raw += 1
        try:
            m = json.loads(line)
        except json.JSONDecodeError:
            continue
        if m.get("msg_id"):
            seen[m["msg_id"]] = m

    acked = load_msg_id_set(INBOX_DIR / "_acks.jsonl")
    unacked = [m for mid, m in seen.items() if mid not in acked]

    print(f"# {inbox}")
    print(
        f"# raw_lines={raw}  unique_msgs={len(seen)}  "
        f"unacked={len(unacked)}  acked={len(seen) - len(unacked)}"
    )
    print()
    for m in sorted(unacked, key=lambda x: x.get("ts", "")):
        intent = m.get("intent", "?")
        repo = m.get("repo", "?")
        pr = m.get("pr") or "-"
        ts = m.get("ts", "")[:19]
        reason = (m.get("payload") or {}).get("reason", "")
        print(f"  [{ts}] {intent:9s} {repo}#{pr}  {reason}")


@inbox_app.callback(invoke_without_command=True)
def inbox_default(
    ctx: typer.Context,
    actor: str = typer.Argument(None, help="triaged | investigate | qa | drip | respondable | retro"),
) -> None:
    """Read ~/.sweep/inbox/<actor>.jsonl, dedupe by msg_id."""
    if actor is None:
        print(ctx.get_help())
        raise typer.Exit(0)
    valid = {"triaged", "investigate", "qa", "drip", "respondable", "retro"}
    if actor not in valid:
        raise typer.BadParameter(
            f"unknown actor {actor!r}; pick one of {'|'.join(sorted(valid))}"
        )
    _inspect(actor)
