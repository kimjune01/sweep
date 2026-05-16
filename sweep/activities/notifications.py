"""GitHub notifications poller — cheap push-ish alternative to scanning
every open PR on a cadence.

GitHub's unread bit is the cross-restart watermark. `poll_github_notifications`
fetches unread threads; `mark_thread_read` is the ack — only called after the
downstream pr-state classify+deliver succeeds. If the pipe is down or wedged,
threads stay unread; next poll re-fetches them. Idempotent by construction.

We don't persist a `since` cursor on disk: correctness comes from
unread-state, not from a watermark. The `since` parameter (if any) is an
in-memory optimization for one workflow run.
"""

from __future__ import annotations

import asyncio
import json
import subprocess

from temporalio import activity

from sweep import observe


# GitHub's documented minimum honored poll interval. Faster polls just
# burn rate limit on 304s. The X-Poll-Interval response header can bump
# this higher under load — we don't parse it; if GitHub bumps it we'll
# notice via rate-limit pressure and adjust the constant.
POLL_INTERVAL_S = 60


def _parse_repo_pr(subject_url: str) -> tuple[str, int] | None:
    """https://api.github.com/repos/owner/name/pulls/123 → ("owner/name", 123).
    Returns None for non-PR URLs."""
    # Defensive: only PullRequest threads should reach here, but the URL
    # is the only authoritative source for the number.
    marker = "/repos/"
    i = subject_url.find(marker)
    if i < 0:
        return None
    tail = subject_url[i + len(marker):]
    parts = tail.split("/")
    if len(parts) < 4 or parts[2] != "pulls":
        return None
    try:
        return f"{parts[0]}/{parts[1]}", int(parts[3])
    except ValueError:
        return None


@activity.defn
async def poll_github_notifications(since_iso: str | None = None) -> dict:
    """Fetch unread PR notifications. Returns a dict with `threads`
    (list of {thread_id, repo, pr, updated_at, reason}) and
    `poll_interval_s`. Only PullRequest threads; issues/discussions/
    releases are dropped here (pr-state is PR-only).

    `since_iso` is an optimization: GitHub returns threads updated at or
    after this timestamp. Omit on cold start — GitHub returns all unread.
    """
    args = ["gh", "api", "/notifications", "-X", "GET",
            "-F", "all=false", "-F", "per_page=50"]
    if since_iso:
        args += ["-F", f"since={since_iso}"]
    try:
        proc = await asyncio.to_thread(
            subprocess.run, args, capture_output=True, text=True,
            timeout=30, check=True,
        )
    except subprocess.CalledProcessError as e:
        observe.event("notifications_poll_failed",
                      error=(e.stderr or "")[:300])
        return {"threads": [], "poll_interval_s": POLL_INTERVAL_S}
    except subprocess.TimeoutExpired:
        observe.event("notifications_poll_failed", error="timeout")
        return {"threads": [], "poll_interval_s": POLL_INTERVAL_S}

    try:
        raw = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        observe.event("notifications_poll_failed", error="bad_json")
        return {"threads": [], "poll_interval_s": POLL_INTERVAL_S}

    threads: list[dict] = []
    for t in raw:
        subject = t.get("subject") or {}
        if subject.get("type") != "PullRequest":
            continue
        parsed = _parse_repo_pr(subject.get("url") or "")
        if not parsed:
            continue
        repo, pr = parsed
        threads.append({
            "thread_id": str(t.get("id", "")),
            "repo": repo,
            "pr": pr,
            "updated_at": t.get("updated_at", ""),
            "reason": t.get("reason", ""),
        })
    return {"threads": threads, "poll_interval_s": POLL_INTERVAL_S}


@activity.defn
async def mark_thread_read(thread_id: str) -> bool:
    """Mark one notification thread as read. This is the ack —
    GitHub stops returning it from /notifications. Only call after
    downstream processing has succeeded.

    Returns True on success, False on failure (caller decides whether
    to retry; not advancing the watermark just means we re-process
    next tick, which is harmless given inbox dedup)."""
    if not thread_id:
        return False
    try:
        await asyncio.to_thread(
            subprocess.run,
            ["gh", "api", "-X", "PATCH", f"/notifications/threads/{thread_id}"],
            capture_output=True, text=True, timeout=15, check=True,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        err = getattr(e, "stderr", "") or str(e)
        observe.event("notification_ack_failed",
                      thread_id=thread_id, error=err[:200])
        return False
