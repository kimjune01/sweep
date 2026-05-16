"""`sweep inbox` — operator's human inbox.

  bare              → "what you owe": actionable retros + respondable PRs.
                       Same list cockpit shows under the table; this is
                       the standalone version for when you only want the
                       todo and not the rest of the dashboard.
  inbox actor <n>   → low-level inspector: dump one actor's inbox jsonl,
                       dedupe by msg_id, show acked vs unacked.
"""

from __future__ import annotations

import json

import typer

from sweep import retro_state
from sweep.inbox_state import INBOX_DIR, inbox_states, load_msg_id_set


# Per-intent glyphs for the respondable list. Mirrors cockpit so both
# views read the same way.
RESPONDABLE_GLYPHS = {
    "respond":      "💬",
    "force-push":   "⬆️",
    "manual-merge": "🤝",
    "sign-off":     "🖋",
}


inbox_app = typer.Typer(
    help="Operator inbox — what you owe right now.",
    no_args_is_help=False,
    invoke_without_command=True,
)


def operator_inbox_lines() -> list[str]:
    """Markdown bullets for the human inbox: actionable retros first,
    then respondable PRs. Shared with `sweep cockpit` so both surfaces
    render the same items the same way."""
    lines: list[str] = []
    for r in retro_state.list_retros():
        if not retro_state.has_prescription(r):
            continue
        lines.append(f"- 🌱 [retro {r.name}]({r.path.as_uri()})")

    s = inbox_states("respondable")
    msgs = sorted(s.get("queued", []) + s.get("in_flight", []),
                  key=lambda m: m.get("ts", ""))
    for m in msgs:
        repo = m.get("repo", "?")
        pr = m.get("pr") or "-"
        intent = m.get("intent", "")
        payload = m.get("payload") or {}
        reason = payload.get("reason", "")
        url = f"https://github.com/{repo}/pull/{pr}"
        glyph = RESPONDABLE_GLYPHS.get(intent, "·")
        suffix = f" — {reason}" if reason else ""
        lines.append(f"- {glyph} [{repo}#{pr}]({url}){suffix}")
    return lines


@inbox_app.callback(invoke_without_command=True)
def inbox_default(ctx: typer.Context) -> None:
    """What you owe: actionable retros + respondable PRs."""
    if ctx.invoked_subcommand is not None:
        return
    lines = operator_inbox_lines()
    if not lines:
        print("# inbox — empty")
        return
    print("# inbox")
    print()
    for line in lines:
        print(line)


@inbox_app.command("actor")
def actor_inspect(
    actor: str = typer.Argument(..., help="triaged | investigate | qa | drip | respondable | retro"),
) -> None:
    """Dump one actor's inbox jsonl, dedupe by msg_id, show acked vs unacked."""
    valid = {"triaged", "investigate", "qa", "drip", "respondable", "retro"}
    if actor not in valid:
        raise typer.BadParameter(
            f"unknown actor {actor!r}; pick one of {'|'.join(sorted(valid))}"
        )
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
