"""`sweep tissue` — operator approval surface for side-hatch comments.

Tissue actor drafts polite issue comments from no-fix investigations.
Drafts land in `~/.sweep/inbox/tissue-drafts.jsonl` awaiting approval —
this CLI is the human gate. Approving posts via `gh issue comment` and
records the result in attestations. Discarding drops the draft.

Honors `sweep dry`: in dry mode, `approve` writes to the dry inbox
instead of posting. Acks happen either way so the draft drains.

Same shape as drip's approval surface — list / approve / discard — so
the operator interaction model stays uniform across side-hatches.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path

import typer

from sweep import control_state, observe


DRAFTS_PATH = Path.home() / ".sweep" / "inbox" / "tissue-drafts.jsonl"
ACKS_PATH = Path.home() / ".sweep" / "inbox" / "_acks.jsonl"


tissue_app = typer.Typer(
    help="Tissue — side-hatch comments awaiting operator approval",
    no_args_is_help=True,
)


def _load_drafts() -> list[dict]:
    if not DRAFTS_PATH.exists():
        return []
    out: list[dict] = []
    for line in DRAFTS_PATH.read_text().splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _load_acked_ids() -> set[str]:
    if not ACKS_PATH.exists():
        return set()
    acked: set[str] = set()
    for line in ACKS_PATH.read_text().splitlines():
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        mid = d.get("draft_id") or d.get("msg_id")
        if mid:
            acked.add(mid)
    return acked


def _ack(draft_id: str, outcome: str, **extra) -> None:
    """Append an ack record so the draft drops out of `list`."""
    ACKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "draft_id": draft_id,
        "ts":       dt.datetime.now(dt.timezone.utc).isoformat(),
        "from":     "tissue-cli",
        "outcome":  outcome,
        **extra,
    }
    with open(ACKS_PATH, "a") as f:
        f.write(json.dumps(rec) + "\n")


@tissue_app.command("list")
def tissue_list() -> None:
    """Show pending tissue drafts — repo, issue, char count, comment preview."""
    drafts = _load_drafts()
    acked = _load_acked_ids()
    pending = [d for d in drafts if d.get("draft_id") not in acked]
    if not pending:
        typer.echo("# Tissue drafts\n\n_No pending drafts._")
        return
    lines = [f"# Tissue drafts ({len(pending)} pending)", ""]
    for d in pending:
        comment = (d.get("comment") or "").strip()
        preview = comment.replace("\n", " ")
        if len(preview) > 200:
            preview = preview[:197] + "..."
        lines.append(
            f"- **{d.get('repo')}#{d.get('issue')}**  "
            f"`{d.get('draft_id')}`  ({d.get('draft_chars', 0)} chars)"
        )
        lines.append(f"  > {preview}")
        lines.append(f"  https://github.com/{d.get('repo')}/issues/{d.get('issue')}")
        lines.append("")
    lines.append("")
    lines.append("_`sweep tissue approve <draft_id>` to post, "
                 "`sweep tissue discard <draft_id>` to drop._")
    typer.echo("\n".join(lines))


def _find_draft(draft_id: str) -> dict | None:
    for d in _load_drafts():
        if d.get("draft_id") == draft_id:
            return d
    return None


@tissue_app.command("approve")
def tissue_approve(
    draft_id: str = typer.Argument(..., help="Draft id from `sweep tissue list`"),
) -> None:
    """Approve a draft: deposit it on the post inbox + signal post-actor.
    Posting itself happens in `post_cycle` — the CLI's job is just the
    human gate. Separation of concerns: drafting (tissue) and posting
    (post) are different actors with different failure modes, different
    blast radius. The CLI doesn't touch gh."""
    import asyncio
    from sweep.activities.tissue import enqueue_post

    acked = _load_acked_ids()
    if draft_id in acked:
        typer.echo(f"draft {draft_id} already acked")
        raise typer.Exit(0)
    draft = _find_draft(draft_id)
    if not draft:
        typer.echo(f"no draft with id {draft_id}", err=True)
        raise typer.Exit(2)
    repo = draft.get("repo", "")
    issue = int(draft.get("issue", 0))
    try:
        wf_id = asyncio.run(enqueue_post(draft))
    except Exception as e:
        typer.echo(f"enqueue failed: {e}", err=True)
        raise typer.Exit(1)
    observe.event("tissue_approved", draft_id=draft_id,
                  repo=repo, issue=issue,
                  draft_chars=len(draft.get("comment", "")))
    _ack(draft_id, "approved", repo=repo, issue=issue,
         post_signal=str(wf_id))
    if wf_id:
        typer.echo(f"approved {draft_id} → enqueued to post-actor")
    else:
        typer.echo(f"approved {draft_id} → enqueued to post inbox "
                   f"(signal pending — actor will catch on next drain)")


@tissue_app.command("discard")
def tissue_discard(
    draft_id: str = typer.Argument(..., help="Draft id from `sweep tissue list`"),
    reason: str = typer.Option("", "--reason", help="Optional drop reason"),
) -> None:
    """Drop the draft without posting. Acks so it falls off `list`."""
    acked = _load_acked_ids()
    if draft_id in acked:
        typer.echo(f"draft {draft_id} already acked")
        raise typer.Exit(0)
    draft = _find_draft(draft_id)
    if not draft:
        typer.echo(f"no draft with id {draft_id}", err=True)
        raise typer.Exit(2)
    observe.event("tissue_discarded", draft_id=draft_id,
                  repo=draft.get("repo"), issue=draft.get("issue"),
                  reason=reason[:200])
    _ack(draft_id, "discarded", reason=reason[:200],
         repo=draft.get("repo"), issue=draft.get("issue"))
    typer.echo(f"discarded {draft_id}")
