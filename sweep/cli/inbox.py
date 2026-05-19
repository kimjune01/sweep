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
            # Prefer the artifact's per-card summary over the generic
            # reason — summary carries the actual halt line ("Frontier
            # closed at depth 1", "blocked on CLA", etc.), while reason
            # is the routing-stage explanation. Both fall back cleanly.
            summary = (payload.get("summary") or "").strip()
            reason = payload.get("reason", "")
            tail = summary or reason
            if summary and reason and summary != reason:
                tail = f"{summary}  _({reason})_"
            suffix = f" — {tail[:200]}" if tail else ""
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
   rope ▸ roll ▸ sift ▸ triage

   triage ┬▸ investigate ▸ switch
          └▸ immunize ▸ comment-issue ▸ post

   switch ┬▸ qa ▸ attest ▸ compose ▸ submit ▸ push
          ├▸ comment-issue ▸ post
          └▸ human

 engagement (post-submit)
   notifs ▸ remit ┬▸ respond
                  ├▸ reqa ▸ attest
                  ├▸ reinvestigate ▸ reqa
                  ├▸ amend
                  └▸ human

 side-channels
   leakdog ▸ bless ┬▸ comment-issue-drafts ▸ post
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
    as_json: bool = typer.Option(False, "--json", help="Emit unacked cards as JSON for the TUI overlay"),
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

    ordered = sorted(unacked, key=lambda x: x.get("ts", ""))
    if as_json:
        out = [{
            "msg_id": m.get("msg_id"), "repo": m.get("repo"),
            "pr": m.get("pr"), "intent": m.get("intent"),
            "reason": (m.get("payload") or {}).get("reason", ""),
            "cmd": next((m.get("payload", {}).get(k) for k in (m.get("payload") or {})
                         if k == "cmd" or k.endswith("_cmd")), ""),
        } for m in ordered]
        print(json.dumps(out))
        return

    print(f"# {inbox}")
    print(
        f"# raw_lines={raw}  unique_msgs={len(seen)}  "
        f"unacked={len(unacked)}  acked={len(seen) - len(unacked)}"
    )
    print()
    for i, m in enumerate(ordered, 1):
        intent = m.get("intent", "?")
        repo = m.get("repo", "?")
        pr = m.get("pr") or "-"
        ts = m.get("ts", "")[:19]
        payload = m.get("payload") or {}
        reason = payload.get("reason", "")
        print(f"  [{i:>2}] [{ts}] {intent:9s} {repo}#{pr}  {reason}")
        # Copy-paste line: surface concrete commands when the card
        # carries one. Convention: payload fields named *_cmd or `cmd`
        # are runnable shell snippets the operator pastes verbatim.
        cmd_keys = [k for k in payload
                    if k == "cmd" or k.endswith("_cmd")]
        for ck in cmd_keys:
            cmd = (payload.get(ck) or "").strip()
            if cmd:
                print(f"       $ {cmd}")

    # Persist the indexed list so `sweep inbox done <N>` resolves the
    # same way `sweep pr <N>` resolves against recent_lanes.json. One
    # entry per displayed card; only unacked since that's what `done`
    # would target.
    if actor == "human":
        from pathlib import Path as _P
        state_dir = _P.home() / ".sweep" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        idx = [{"msg_id": m.get("msg_id"), "repo": m.get("repo"),
                "pr": m.get("pr")} for m in ordered]
        try:
            (state_dir / "recent_inbox.json").write_text(json.dumps(idx))
        except OSError:
            pass


@inbox_app.command("done")
def inbox_done(
    ref: str = typer.Argument(..., help="<N> from last `sweep inbox actor human`, or owner/repo#PR"),
) -> None:
    """Ack every unacked human-inbox card matching the ref AND re-remit
    the PR so the substrate re-observes world-state. "Operator action
    complete" is not the same as "world is in the expected state" — let
    remit reclassify and route from current truth."""
    import re as _re
    from pathlib import Path as _P
    from sweep.inbox_state import INBOX_DIR as _INBOX
    import datetime as _dt
    import asyncio as _asyncio

    recent_path = _P.home() / ".sweep" / "state" / "recent_inbox.json"

    # Resolve ref → (repo, pr).
    int_re = _re.compile(r"^\d+$")
    pr_re = _re.compile(r"^([\w.-]+/[\w.-]+)#(\d+)$")
    if int_re.match(ref):
        if not recent_path.exists():
            raise typer.BadParameter(
                f"no recent inbox index; run `sweep inbox actor human` first"
            )
        try:
            entries = json.loads(recent_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            raise typer.BadParameter(f"recent inbox index unreadable: {e}")
        idx = int(ref)
        if not (1 <= idx <= len(entries)):
            raise typer.BadParameter(
                f"index {idx} out of range; last render had {len(entries)} unacked cards"
            )
        e = entries[idx - 1]
        repo, pr = e.get("repo"), e.get("pr")
    else:
        m = pr_re.match(ref)
        if not m:
            raise typer.BadParameter(f"expected <N> or owner/repo#PR, got {ref!r}")
        repo, pr = m.group(1), int(m.group(2))

    if not repo or not pr:
        raise typer.BadParameter(f"resolved ref has no repo/pr: {ref}")

    inbox = _INBOX / "human.jsonl"
    acks = _INBOX / "_acks.jsonl"
    if not inbox.exists():
        print("(no human inbox file)")
        return

    already_acked = load_msg_id_set(acks)
    to_ack: list[str] = []
    for line in inbox.read_text().splitlines():
        if not line.strip(): continue
        try: m = json.loads(line)
        except json.JSONDecodeError: continue
        if m.get("msg_id") in already_acked: continue
        if m.get("repo") == repo and m.get("pr") == pr:
            to_ack.append(m.get("msg_id"))

    if not to_ack:
        print(f"  no unacked cards for {repo}#{pr}")
        return

    ts = _dt.datetime.now(_dt.timezone.utc).isoformat()
    with open(acks, "a") as f:
        for mid in to_ack:
            f.write(json.dumps({
                "msg_id": mid, "ts": ts, "from": "operator-action",
                "outcome": "action-complete; re-remitted",
            }) + "\n")
    print(f"  acked {len(to_ack)} card(s) for {repo}#{pr}")

    # Re-remit so remit-actor re-observes PR state and re-classifies.
    # Skip when the number is an issue, not a PR — remit would crash
    # on the gh pr view. Investigate-decision cards often carry the
    # source issue number, not a PR.
    import subprocess as _sp
    pr_check = _sp.run(
        ["gh", "pr", "view", str(pr), "-R", repo, "--json", "number"],
        capture_output=True, text=True, timeout=15,
    )
    if pr_check.returncode != 0:
        print(f"  skipped re-remit: {repo}#{pr} is not a PR "
              f"(likely an issue number)")
        return
    async def _kick():
        from sweep.activities.remit import kick_remit_card
        return await kick_remit_card(repo, pr, sender="operator-done")
    wf = _asyncio.run(_kick())
    print(f"  re-remitted: {wf or '(no wf)'}")
