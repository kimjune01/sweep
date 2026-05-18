"""`sweep inbox` — operator's human inbox.

  bare              → "what you owe": actionable retros + human-bucket PRs.
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


# Per-intent glyphs for the human inbox list. Mirrors cockpit so both
# views read the same way.
HUMAN_GLYPHS = {
    "respond":      "💬",
    "force-push":   "⬆️",
    "manual-merge": "🤝",
    "sign-off":     "🖋",
    "retro-summary": "📊",
}


inbox_app = typer.Typer(
    help="Operator inbox — what you owe right now.",
    no_args_is_help=False,
    invoke_without_command=True,
)


def operator_inbox_lines() -> list[str]:
    """Markdown bullets for the human inbox: actionable retros first,
    then human-bucket PRs. Shared with `sweep cockpit` so both surfaces
    render the same items the same way."""
    lines: list[str] = []
    for r in retro_state.list_retros():
        if not retro_state.has_prescription(r):
            continue
        lines.append(f"- 🌱 [retro {r.name}]({r.path.as_uri()})")

    s = inbox_states("human")
    msgs = sorted(s.get("queued", []) + s.get("in_flight", []),
                  key=lambda m: m.get("ts", ""))
    for m in msgs:
        intent = m.get("intent", "")
        payload = m.get("payload") or {}
        glyph = HUMAN_GLYPHS.get(intent, "·")
        repo = m.get("repo")
        pr = m.get("pr")
        # Per-PR cards: render the GitHub link the operator clicks
        # to act on it. Repo+pr are the per-PR contract.
        if repo and pr:
            url = f"https://github.com/{repo}/pull/{pr}"
            reason = payload.get("reason", "")
            suffix = f" — {reason}" if reason else ""
            lines.append(f"- {glyph} [{repo}#{pr}]({url}){suffix}")
            continue
        # Pipeline-wide cards (retro-summary, future system notes):
        # no PR to link to. Render a short label + an excerpt from the
        # payload so the operator can decide whether to drill in.
        ts = (m.get("ts") or "")[:16].replace("T", " ")
        if intent == "retro-summary":
            tail = (payload.get("stdout_tail") or "").strip()
            first_line = next((ln for ln in tail.splitlines() if ln.strip()),
                              "no summary")
            excerpt = first_line[:140] + ("…" if len(first_line) > 140 else "")
            since = payload.get("since", "?")
            lines.append(f"- {glyph} retro {ts} (since {since}) — {excerpt}")
            continue
        # Unknown shape with no per-PR identity: render the intent +
        # timestamp so it's at least discoverable, not silently lying.
        lines.append(f"- {glyph} {intent or 'unknown-intent'} {ts}")
    return lines


# Static architecture diagram shown when the human inbox is empty.
# Empty inbox = pipe is humming without needing you, so we use the
# real estate to explain the shape of the system instead of repeating
# counts that cockpit/lanes already render.
_ARCHITECTURE_DIAGRAM = """\
```
 production
   rope ▸ scout ▸ sift ▸ triage ▸ investigate ▸ qa ▸ attest ▸ compose ▸ submit ▸ push
    ▲              └──┬──┘                       │
    │                 ▼                          ▼
    │              immunize ▸ tissue ▸ post
    │
    └── idle signals from investigate / qa (rope regulates scout depth)

 engagement (post-submit)
   notifs ▸ remit ┬▸ respond         auto: rebase / close / clarify
                  ├▸ reqa ▸ attest   re-attest on CI flip
                  ├▸ reinvestigate   maintainer raised a new in-PR concern
                  ├▸ amend           splice attestation footer into PR body
                  └▸ human           you — the manual peer to respond

 side-channels
   leakdog ▸ bless ┬▸ tissue-drafts ▸ post
                   └▸ human-issues

   · dry holds at submit · everything else flows on real-world time
```
"""


@inbox_app.callback(invoke_without_command=True)
def inbox_default(ctx: typer.Context) -> None:
    """What you owe: actionable retros + human-bucket PRs."""
    if ctx.invoked_subcommand is not None:
        return
    lines = operator_inbox_lines()
    print(f"# inbox ({len(lines)})")
    if not lines:
        print()
        print(_ARCHITECTURE_DIAGRAM)
        return
    print()
    for line in lines:
        print(line)


@inbox_app.command("actor")
def actor_inspect(
    actor: str = typer.Argument(..., help="triaged | investigate | qa | respond | human | retro"),
) -> None:
    """Dump one actor's inbox jsonl, dedupe by msg_id, show acked vs unacked."""
    valid = {"triaged", "investigate", "qa", "respond", "human", "retro"}
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
