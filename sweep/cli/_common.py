"""Shared helpers across CLI subcommands."""

from __future__ import annotations

import json
import subprocess
import uuid

from sweep.types import QaOneEntryRequest


SWEEP_TASK_QUEUE = "sweep-tq"
QA_ACTOR_ID = "qa-actor"
RESPOND_ACTOR_ID = "respond-actor"
REMIT_ACTOR_ID = "remit-actor"
SUBMIT_ACTOR_ID = "submit-actor"
COMPOSE_ACTOR_ID = "compose-actor"
ROPE_ACTOR_ID = "rope-actor"
TRIAGE_ACTOR_ID = "triage-actor"
INVESTIGATE_ACTOR_ID = "investigate-actor"
REINVESTIGATE_ACTOR_ID = "reinvestigate-actor"
REQA_ACTOR_ID = "reqa-actor"
SIFT_ACTOR_ID = "sift-actor"
SCOUT_ACTOR_ID = "scout-actor"
TISSUE_ACTOR_ID = "tissue-actor"
POST_ACTOR_ID = "post-actor"
IMMUNIZE_ACTOR_ID = "immunize-actor"
BLESS_ACTOR_ID = "bless-actor"
USAGE_POLLER_ID = "usage-poller"
NOTIFICATION_POLLER_ID = "notification-poller"
LEAKDOG_DAEMON_ID = "leakdog-daemon"


def new_msg_id() -> str:
    return f"dev-{uuid.uuid4().hex[:8]}"


def build_req(repo: str, branch: str, worktree: str, test_cmd: str, msg_id: str | None) -> QaOneEntryRequest:
    return QaOneEntryRequest(
        msg_id=msg_id or new_msg_id(),
        repo=repo,
        branch=branch,
        worktree=worktree,
        test_cmd=test_cmd,
        issue=None,
    )


def git_diff(worktree: str) -> str:
    return subprocess.run(
        ["git", "-C", worktree, "diff", "origin/HEAD..."],
        capture_output=True, text=True,
    ).stdout


def print_json(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))
