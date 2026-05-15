"""Idempotency for non-idempotent external effects.

Temporal retries activities on failure. For idempotent ops (git checkout,
file write, pytest), retry is harmless. For mutating remote ops (gh pr
create, slack post, mail send), retry creates duplicates.

The pattern: tag every external effect with the workflow's msg_id, check
the remote for an existing tag before creating, and treat "tag found" as
success without re-creating.

This is the "exactly-once observable effect" contract on top of
at-least-once delivery.
"""

from __future__ import annotations

import re
import subprocess


TAG_PREFIX = "sweep-msg-id"


def embed_tag(content: str, msg_id: str) -> str:
    """Embed an HTML-comment tag in the content.

    Works for: PR/issue bodies, commit messages (use raw form below).
    Idempotent: embedding twice is fine, the find_in() helper ignores dupes.
    """
    return f"{content.rstrip()}\n\n<!-- {TAG_PREFIX}: {msg_id} -->\n"


def commit_trailer(msg_id: str) -> str:
    """Git-trailer form for commit messages."""
    return f"Sweep-Msg-Id: {msg_id}"


def find_in(text: str) -> str | None:
    """Extract the msg_id tag from text. Returns the msg_id or None."""
    m = re.search(rf"<!--\s*{TAG_PREFIX}:\s*([\w\-:.]+)\s*-->", text)
    if m:
        return m.group(1)
    m = re.search(rf"Sweep-Msg-Id:\s*([\w\-:.]+)", text)
    if m:
        return m.group(1)
    return None


def existing_pr_for_msg_id(repo: str, msg_id: str) -> int | None:
    """Check if a PR with this msg_id already exists in the repo. Returns PR number or None.

    Use *before* calling `gh pr create` so retry-after-network-failure doesn't
    produce a duplicate PR.
    """
    out = subprocess.run(
        [
            "gh", "pr", "list",
            "--repo", repo,
            "--author", "@me",
            "--state", "all",
            "--search", msg_id,
            "--json", "number,body",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode != 0:
        return None
    import json
    try:
        prs = json.loads(out.stdout or "[]")
    except json.JSONDecodeError:
        return None
    for pr in prs:
        if find_in(pr.get("body") or "") == msg_id:
            return int(pr["number"])
    return None
