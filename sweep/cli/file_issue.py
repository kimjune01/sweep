"""`sweep file-issue …` — operator-facing surface for the file-issue actor.

`list`     — pending drafts
`show`     — print one draft for review
`approve`  — post a draft as a GitHub issue + record in hold-issue holding bin
`discard`  — drop a draft without posting

Posting is inline (subprocess `gh issue create`) rather than via a
separate post-actor: file-issue's volume is low, and split-actor
concerns matter less when the gh call is the only side effect. If
volume grows or failure modes diverge from "succeeds or doesn't,"
reify a post_file_issue_cycle later.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import typer

from sweep import hold_issue_registry, observe

file_issue_app = typer.Typer(
    help="file-issue actor — fresh-issue drafts, approval, post.",
    no_args_is_help=True,
)


DRAFTS = Path.home() / ".sweep" / "inbox" / "file-issue-drafts.jsonl"
APPROVED = Path.home() / ".sweep" / "state" / "file_issue_approved.json"
DISCARDED = Path.home() / ".sweep" / "state" / "file_issue_discarded.json"


def _load_drafts() -> list[dict]:
    if not DRAFTS.exists():
        return []
    out: list[dict] = []
    for line in DRAFTS.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _load_set(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        return set(json.loads(path.read_text()))
    except (json.JSONDecodeError, OSError):
        return set()


def _save_set(path: Path, s: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(s)))


def _pending(drafts: list[dict]) -> list[dict]:
    approved = _load_set(APPROVED)
    discarded = _load_set(DISCARDED)
    return [d for d in drafts if d["draft_id"] not in approved
            and d["draft_id"] not in discarded]


@file_issue_app.command("list")
def file_issue_list() -> None:
    """Pending file-issue drafts awaiting operator approval."""
    pending = _pending(_load_drafts())
    if not pending:
        print("# no pending file-issue drafts")
        return
    print(f"# file-issue drafts ({len(pending)} pending)")
    print()
    print("| # | draft_id | target | source | title |")
    print("|---|----------|--------|--------|-------|")
    for i, d in enumerate(pending, 1):
        title = (d.get("title") or "")[:60].replace("|", "\\|")
        print(f"| {i} | `{d['draft_id']}` | `{d['target_repo']}` | "
              f"`{d['source_investigation']}` | {title} |")


@file_issue_app.command("show")
def file_issue_show(draft_id: str = typer.Argument(...)) -> None:
    """Print one draft for review (title + body)."""
    for d in _load_drafts():
        if d["draft_id"] == draft_id:
            print(f"# Draft: {draft_id}")
            print(f"- target_repo:    {d['target_repo']}")
            print(f"- source:         {d['source_investigation']}")
            print(f"- source_hygraph: {d['source_hygraph_path']}")
            print(f"- body_chars:     {d['body_chars']}")
            print()
            print(f"## Title")
            print()
            print(d.get("title", ""))
            print()
            print(f"## Body")
            print()
            print(d.get("body", ""))
            return
    print(f"_no draft with id {draft_id}_")


@file_issue_app.command("approve")
def file_issue_approve(draft_id: str = typer.Argument(...)) -> None:
    """Post the draft as a GitHub issue and record the filing in the
    hold-issue holding bin. Marks the draft approved so it doesn't
    re-list."""
    drafts = _load_drafts()
    target = next((d for d in drafts if d["draft_id"] == draft_id), None)
    if target is None:
        raise typer.BadParameter(f"no draft with id {draft_id}")
    approved = _load_set(APPROVED)
    if draft_id in approved:
        print(f"_draft {draft_id} already approved_")
        return

    repo = target["target_repo"]
    title = target["title"]
    body = target["body"]
    try:
        proc = subprocess.run(
            ["gh", "issue", "create", "--repo", repo,
             "--title", title, "--body", body],
            capture_output=True, text=True, timeout=60, check=False,
        )
    except FileNotFoundError:
        observe.event("file_issue_post_failed", draft_id=draft_id,
                      reason="gh not on PATH")
        raise typer.Exit(1)
    if proc.returncode != 0:
        observe.event("file_issue_post_failed", draft_id=draft_id, repo=repo,
                      stderr=(proc.stderr or "")[:300])
        print(f"gh issue create failed: {(proc.stderr or '')[:200]}")
        raise typer.Exit(1)

    url = (proc.stdout or "").strip()
    issue_num = None
    try:
        issue_num = int(url.rsplit("/", 1)[-1])
    except (ValueError, IndexError):
        observe.event("file_issue_post_parse_failed", draft_id=draft_id,
                      stdout=url[:200])
        print(f"gh succeeded but URL was unparseable: {url}")
        raise typer.Exit(1)

    hold_issue_registry.record(
        repo=repo, issue_num=issue_num, title=title, url=url,
        draft_id=draft_id,
        source_hygraph_path=target["source_hygraph_path"],
        source_investigation=target["source_investigation"],
    )
    approved.add(draft_id)
    _save_set(APPROVED, approved)
    observe.event("issue_filed", repo=repo, issue=issue_num,
                  draft_id=draft_id, url=url)
    print(f"# Filed {repo}#{issue_num}")
    print(f"- url: {url}")
    print(f"- holding bin: ~/.sweep/hold-issue.jsonl")


@file_issue_app.command("discard")
def file_issue_discard(draft_id: str = typer.Argument(...)) -> None:
    """Drop a draft without posting."""
    drafts = _load_drafts()
    if not any(d["draft_id"] == draft_id for d in drafts):
        raise typer.BadParameter(f"no draft with id {draft_id}")
    discarded = _load_set(DISCARDED)
    discarded.add(draft_id)
    _save_set(DISCARDED, discarded)
    observe.event("file_issue_draft_discarded", draft_id=draft_id)
    print(f"discarded {draft_id}")
