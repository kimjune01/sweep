"""`sweep andon` — list / clear actor halt markers.

Halt markers live at ~/.sweep/control/andon/<actor>.json, one file per
halted actor, written by the actor's andon path via `record_andon`.
Cockpit reads this dir to flash the red banner; this command lets the
operator inspect details and clear once the underlying issue is fixed.

`clear <actor>` signals the actor's `clear_andon` (which the workflow
maps to removing the marker), so the marker and the workflow's in-memory
`halted` flag get reset together — no chance of clearing the banner
without resuming the line, or vice versa.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from sweep.cli._common import (
    AMEND_ACTOR_ID,
    ATTEST_ACTOR_ID,
    BLESS_ACTOR_ID,
    CHECK_ACTOR_ID,
    COMPOSE_ACTOR_ID,
    HEART_ACTOR_ID,
    IMMUNIZE_ACTOR_ID,
    INVESTIGATE_ACTOR_ID,
    POST_ACTOR_ID,
    QA_ACTOR_ID,
    REINVESTIGATE_ACTOR_ID,
    REMIT_ACTOR_ID,
    REQA_ACTOR_ID,
    RESPOND_ACTOR_ID,
    RETRO_ACTOR_ID,
    ROPE_ACTOR_ID,
    SCOUT_ACTOR_ID,
    SIFT_ACTOR_ID,
    SUBMIT_ACTOR_ID,
    COMMENT_ISSUE_ACTOR_ID,
    TRIAGE_ACTOR_ID,
)
from sweep.system import TEMPORAL_ADDR


andon_app = typer.Typer(
    help="Inspect and clear actor andon halts.",
    no_args_is_help=True,
)


ANDON_DIR = Path.home() / ".sweep" / "control" / "andon"


# actor (skill activity name or "qa") → workflow id to signal clear_andon on.
# Every SkillActor-based workflow needs an entry here, else `sweep andon clear`
# can't reach it. Accept both the bare actor name ("attest") and the
# activity-name form ("attest_cycle") so the operator doesn't need to
# remember which the workflow registered under.
_CLEAR_TARGETS = {
    "qa":                  QA_ACTOR_ID,
    "triage":              TRIAGE_ACTOR_ID,
    "triage_cycle":        TRIAGE_ACTOR_ID,
    "respond":             RESPOND_ACTOR_ID,
    "respond_cycle":       RESPOND_ACTOR_ID,
    "investigate":         INVESTIGATE_ACTOR_ID,
    "investigate_cycle":   INVESTIGATE_ACTOR_ID,
    "reinvestigate":       REINVESTIGATE_ACTOR_ID,
    "reinvestigate_cycle": REINVESTIGATE_ACTOR_ID,
    "reqa":                REQA_ACTOR_ID,
    "reqa_cycle":          REQA_ACTOR_ID,
    "attest":              ATTEST_ACTOR_ID,
    "attest_cycle":        ATTEST_ACTOR_ID,
    "amend":               AMEND_ACTOR_ID,
    "amend_cycle":         AMEND_ACTOR_ID,
    "check":               CHECK_ACTOR_ID,
    "check_cycle":         CHECK_ACTOR_ID,
    "heart":               HEART_ACTOR_ID,
    "heart_cycle":         HEART_ACTOR_ID,
    "ping":                "ping-actor",
    "ping_cycle":          "ping-actor",
    "retro":               RETRO_ACTOR_ID,
    "retro_cycle":         RETRO_ACTOR_ID,
    "sift":                SIFT_ACTOR_ID,
    "sift_cycle":          SIFT_ACTOR_ID,
    "scout":               SCOUT_ACTOR_ID,
    "scout_cycle":         SCOUT_ACTOR_ID,
    "comment-issue":              COMMENT_ISSUE_ACTOR_ID,
    "comment_issue_cycle":        COMMENT_ISSUE_ACTOR_ID,
    "post":                POST_ACTOR_ID,
    "post_cycle":          POST_ACTOR_ID,
    "immunize":            IMMUNIZE_ACTOR_ID,
    "immunize_cycle":      IMMUNIZE_ACTOR_ID,
    "bless":               BLESS_ACTOR_ID,
    "bless_cycle":         BLESS_ACTOR_ID,
    "remit":               REMIT_ACTOR_ID,
    "remit_cycle":         REMIT_ACTOR_ID,
    "submit":              SUBMIT_ACTOR_ID,
    "submit_cycle":        SUBMIT_ACTOR_ID,
    "compose":             COMPOSE_ACTOR_ID,
    "compose_cycle":       COMPOSE_ACTOR_ID,
    "rope":                ROPE_ACTOR_ID,
    "rope_cycle":          ROPE_ACTOR_ID,
}


@andon_app.command("list")
def andon_list() -> None:
    """Show every active halt marker (actor, reason, timestamp)."""
    if not ANDON_DIR.exists() or not any(ANDON_DIR.glob("*.json")):
        print("(no andon markers — line is running)")
        return
    for f in sorted(ANDON_DIR.glob("*.json")):
        try:
            d = json.loads(f.read_text())
        except Exception:
            print(f"{f.stem}: (unparseable marker)")
            continue
        print(f"{d.get('actor', f.stem)}")
        print(f"  msg_id : {d.get('msg_id', '?')}")
        print(f"  reason : {d.get('reason', '?')}")
        print(f"  ts     : {d.get('ts', '?')}")


@andon_app.command("clear")
def andon_clear(actor: str = typer.Argument(..., help="Actor name (e.g. triage_cycle, qa)")) -> None:
    """Clear the halt for one actor — signals the workflow's clear_andon,
    which both flips its `halted` flag and removes the marker file. Use
    `sweep andon list` to see actor names.

    Watchdog-style halts (e.g. `budget_sift` from the per-actor budget
    watchdog) have no workflow exception to flip — just remove the
    marker file directly, since the next watchdog tick will re-fire if
    the condition is still bad."""
    from temporalio.client import Client

    wf_id = _CLEAR_TARGETS.get(actor)

    if wf_id is None:
        marker = ANDON_DIR / f"{actor}.json"
        if not marker.exists():
            print(f"unknown actor {actor!r}; known: {sorted(_CLEAR_TARGETS)}")
            raise typer.Exit(1)
        # Watchdog clear: remove the marker and lift the pause if this
        # was the last one (same coupling as clear_andon_marker).
        from sweep.control_state import set_paused
        from sweep import observe
        marker.unlink()
        observe.event("andon_cleared", actor=actor)
        if not any(ANDON_DIR.glob("*.json")):
            set_paused(False)
        print(f"cleared watchdog andon for {actor} (marker removed)")
        return

    async def run() -> None:
        from sweep.workflows.qa_actor import QaActor
        from sweep.workflows.skill_actor import SkillActor
        client = await Client.connect(TEMPORAL_ADDR)
        handle = client.get_workflow_handle(wf_id)
        signal = QaActor.clear_andon if actor == "qa" else SkillActor.clear_andon
        await handle.signal(signal)
        print(f"cleared andon for {actor} (wf={wf_id})")

    asyncio.run(run())
