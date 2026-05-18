"""hold-issue: holding bin for issues the substrate filed on GitHub.

Holding-bin pattern: file IS the registry. No long-lived process owner;
read/write happens against `~/.sweep/hold-issue.jsonl`. See
memory/feedback_file_and_forget.md for the asymmetric posture
(file-and-forget toward maintainer, keep-the-pointer toward substrate).

Naming: `file-issue` is the actor that makes the new issue (action);
`hold-issue` is the holding bin that tracks what was filed (state). The
two names disambiguate the verb from the noun.

Schema per line:
    {
      "ts":                  ISO timestamp
      "repo":                "owner/repo"
      "issue_num":            the GitHub issue number we got back
      "title":                "X happens when Y"
      "url":                  "https://github.com/.../issues/N"
      "draft_id":             draft id from the file-issue actor
      "source_hygraph_path":  absolute path to the source hypothesis graph
      "source_investigation": "owner/repo#N" the original investigated thing
    }
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

REGISTRY = Path.home() / ".sweep" / "hold-issue.jsonl"


def record(*, repo: str, issue_num: int, title: str, url: str,
           draft_id: str, source_hygraph_path: str,
           source_investigation: str) -> dict:
    """Append one filing to the holding bin. Returns the entry."""
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "repo": repo,
        "issue_num": issue_num,
        "title": title,
        "url": url,
        "draft_id": draft_id,
        "source_hygraph_path": source_hygraph_path,
        "source_investigation": source_investigation,
    }
    with REGISTRY.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def read_all() -> list[dict]:
    if not REGISTRY.exists():
        return []
    out: list[dict] = []
    for line in REGISTRY.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def is_our_filing(repo: str, issue_num: int) -> bool:
    """True if (repo, issue_num) appears in the holding bin. Used by
    scout/sift to dedup so the substrate doesn't re-investigate
    issues it filed itself."""
    for r in read_all():
        if r.get("repo") == repo and int(r.get("issue_num", -1)) == int(issue_num):
            return True
    return False


def find(issue_num: int, *, repo: str | None = None) -> dict | None:
    """Lookup by issue_num (optionally constrained by repo). First match wins."""
    for r in read_all():
        if int(r.get("issue_num", -1)) != int(issue_num):
            continue
        if repo and r.get("repo") != repo:
            continue
        return r
    return None
