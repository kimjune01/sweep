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
    DRIP_ACTOR_ID,
    INVESTIGATE_ACTOR_ID,
    QA_ACTOR_ID,
    TRIAGE_ACTOR_ID,
)
from sweep.system import TEMPORAL_ADDR


andon_app = typer.Typer(
    help="Inspect and clear actor andon halts.",
    no_args_is_help=True,
)


ANDON_DIR = Path.home() / ".sweep" / "control" / "andon"


# actor (skill activity name or "qa") → workflow id to signal clear_andon on.
_CLEAR_TARGETS = {
    "qa":                 QA_ACTOR_ID,
    "triage_cycle":       TRIAGE_ACTOR_ID,
    "drip_cycle":         DRIP_ACTOR_ID,
    "investigate_cycle":  INVESTIGATE_ACTOR_ID,
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

    Watchdog-style halts (e.g. `prospect_puller` from the API budget
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
        marker.unlink()
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
