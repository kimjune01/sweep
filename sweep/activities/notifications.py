"""GitHub notifications poller — cheap push-ish alternative to scanning
every open PR on a cadence.

GitHub's unread bit is the cross-restart watermark. `poll_github_notifications`
fetches unread threads; `mark_thread_read` is the ack — only called after the
downstream remit classify+deliver succeeds. If the pipe is down or wedged,
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
    releases are dropped here (remit is PR-only).

    `since_iso` is an optimization: GitHub returns threads updated at or
    after this timestamp. Omit on cold start — GitHub returns all unread.
    """
    from sweep import budget as _budget
    _budget.set_caller("notifications")
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
        s_type = subject.get("type")
        s_url = subject.get("url") or ""
        thread_id = str(t.get("id", ""))
        updated_at = t.get("updated_at", "")
        reason = t.get("reason", "")

        if s_type == "PullRequest":
            parsed = _parse_repo_pr(s_url)
            if not parsed:
                continue
            repo, pr = parsed
            threads.append({
                "kind": "pullrequest",
                "thread_id": thread_id,
                "repo": repo,
                "pr": pr,
                "subject_url": s_url,
                "updated_at": updated_at,
                "reason": reason,
            })
        elif s_type in ("CheckSuite", "WorkflowRun"):
            # CheckSuite / WorkflowRun resolution (subject → repo, sha,
            # PR) lives in `check.kick_check_from_subject` — keeping
            # this module a dumb emitter. We forward the raw subject
            # URL and let the check actor enrich.
            repo = _parse_repo_from_subject_url(s_url)
            if not repo:
                continue
            threads.append({
                "kind": "checksuite",
                "thread_id": thread_id,
                "repo": repo,
                "pr": 0,  # check actor resolves
                "subject_url": s_url,
                "updated_at": updated_at,
                "reason": reason,
            })
        else:
            # Issues, discussions, releases, etc. — not in remit/check's
            # scope. Silently drop; the unread bit stays so a future
            # widening could pick them up.
            continue
    return {"threads": threads, "poll_interval_s": POLL_INTERVAL_S}


def _parse_repo_from_subject_url(subject_url: str) -> str | None:
    """`.../repos/owner/name/<resource>/...` → "owner/name". Used for
    CheckSuite / WorkflowRun subject URLs where the trailing segment
    is the resource id, not a PR number. PR-side parsing stays in
    `_parse_repo_pr`."""
    marker = "/repos/"
    i = subject_url.find(marker)
    if i < 0:
        return None
    tail = subject_url[i + len(marker):]
    parts = tail.split("/")
    if len(parts) < 2:
        return None
    return f"{parts[0]}/{parts[1]}"


@activity.defn
async def mark_thread_read(thread_id: str) -> bool:
    """Mark one notification thread as read. This is the ack —
    GitHub stops returning it from /notifications. Only call after
    downstream processing has succeeded.

    Returns True on success, False on failure (caller decides whether
    to retry; not advancing the watermark just means we re-process
    next tick, which is harmless given inbox dedup)."""
    from sweep import budget as _budget
    _budget.set_caller("notifications")
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
