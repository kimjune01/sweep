"""Supervisor specs — the instantiations of the higher-order `supervise`.

Each spec wires the invariant loop to one target by supplying two callables:
`gather` (the attention channels = andon events + operator-inbox cards) and
`history` (the labeled past decisions to replay against). switch / remit /
compose read local jsonl; the contributor-corpus spec reads `gh`. Same loop,
different parameterization — that's the whole point of the higher-order form.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import re
import subprocess
from pathlib import Path

from sweep import observe
from sweep.supervisor import Observation, SupervisorSpec

EVENTS = Path.home() / ".sweep" / "events.jsonl"
HUMAN_INBOX = Path.home() / ".sweep" / "inbox" / "human.jsonl"
OUTCOME_CACHE = Path.home() / ".sweep" / "supervisor" / "outcome-cache.json"

_WORD = re.compile(r"[a-z]{3,}")
_GOAL = "find interesting work without abandoning any reviewed PR"


def _sig_from_reason(prefix: str, reason: str, n: int = 6) -> str:
    """Cheap deterministic clustering key: prefix + first n alpha words of the
    reason, digits and ids stripped. Same shape of failure -> same key, with
    no model call (the precondition stratum must be free)."""
    words = _WORD.findall((reason or "").lower())[:n]
    return f"{prefix}:" + "-".join(words) if words else f"{prefix}:_"


# ---------------------------------------------------------------- local loaders

def _local_gather(actor_kinds: dict[str, str], inbox_senders: set[str]):
    """Build a `gather` for a local actor. `actor_kinds` maps an andon-ish
    event kind to the field its reason lives in; `inbox_senders` are the
    sender names whose human-inbox cards count as this actor's ambiguous
    channel."""
    def gather() -> list[Observation]:
        out: list[Observation] = []
        # andon channel: confidently-wrong events
        for kind, reason_field in actor_kinds.items():
            for ev in observe.events_recent(limit=4000, kind=kind):
                reason = str(ev.get(reason_field, "") or ev.get("summary", ""))
                case = (f"{ev.get('repo')}#{ev.get('issue') or ev.get('pr')}"
                        if ev.get('repo') else None)
                out.append(Observation(
                    signature=_sig_from_reason(kind, reason),
                    detail=f"{kind}: {reason}"
                           + (f" ({case})" if case else ""),
                    source="andon", case=case,
                ))
        # generic andon_recorded entries name the actor explicitly
        for ev in observe.events_recent(limit=4000, kind="andon_recorded"):
            actor = str(ev.get("actor", ""))
            if not any(s in actor for s in inbox_senders):
                continue
            reason = str(ev.get("reason", ""))
            out.append(Observation(
                signature=_sig_from_reason("andon", reason),
                detail=f"andon[{actor}]: {reason}", source="andon",
                case=ev.get("msg_id")))
        # inbox channel: operator-surfaced ambiguous cards
        if HUMAN_INBOX.exists():
            for line in HUMAN_INBOX.read_text().splitlines():
                if not line.strip():
                    continue
                try:
                    card = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if card.get("sender") not in inbox_senders:
                    continue
                pay = card.get("payload", {})
                reason = str(pay.get("summary") or pay.get("reason") or "")
                case = (f"{card.get('repo')}#{card.get('pr')}"
                        if card.get('repo') else card.get("msg_id"))
                out.append(Observation(
                    signature=_sig_from_reason("inbox", reason),
                    detail=f"inbox: {reason}", source="inbox", case=case))
        return out
    return gather


def _local_history(kind: str, label_field: str, ctx_fields: tuple[str, ...]):
    """Build a `history` for a local actor from its labeled-decision events.
    Each row is {input: ctx summary, bucket: the label it chose}."""
    def history() -> list[dict]:
        rows: list[dict] = []
        for ev in observe.events_recent(limit=4000, kind=kind):
            ctx = {f: ev.get(f) for f in ctx_fields if ev.get(f) not in (None, "")}
            rows.append({"input": ctx, "bucket": ev.get(label_field)})
        return rows
    return history


# ---------------------------------------------------------------- regret channel
#
# The third element of the (before, action, OUTCOME) triple — what turns the
# loop from compression into learning. The andon/inbox channels only catch
# misclassifications that left a trace (something tripped, or the agent
# admitted doubt). A SILENT misclassification — confident wrong bucket, nothing
# downstream tripped — is invisible to them. The regret channel recovers it by
# fetching the real outcome (merged / abandoned / stale) and flagging decisions
# the outcome contradicts. A recurring (action -> contradicting-outcome) shape
# clusters like any other observation and feeds the same four-case switch; the
# proposed encoding flips the wrong action. This is the reward signal of an
# online policy learner, except the policy update is structural code.

# (action, outcome) pairs that are prima-facie surprising — a wrong-looking
# decision in hindsight. Generous on purpose: N>=3 + the LLM switch filter the
# noise. The value is the reason, which the supervisor reads to decide whether
# the disagreement is encodable or genuinely fuzzy.
_SURPRISING: dict[tuple[str, str], str] = {
    ("human-gated", "merged"): "escalated to a human, but the PR merged anyway — attention spent on a self-resolving case",
    ("human", "merged"): "routed to human inbox, but the PR merged anyway — attention spent on a self-resolving case",
    ("no-fix", "merged"): "judged no-fix, but the PR merged — the no-fix call may have been wrong",
    ("wait", "closed_unmerged"): "waited, but the PR was closed unmerged — the wait may have abandoned a salvageable PR",
    ("wait", "merged"): "waited, but the PR merged without our engagement — the wait may have missed a contribution window",
    ("shipped", "closed_unmerged"): "shipped, but the PR was closed unmerged — the fix was not accepted upstream",
    ("reinvestigate", "merged"): "sent back to reinvestigate, but the PR merged as-is — the reinvestigation may have been unnecessary",
}

_STALE_DAYS = 14


def _gh_pr_outcome(repo: str, num: int) -> str | None:
    """Fetch a PR's terminal-ish outcome, cached. Returns one of merged /
    closed_unmerged / open_stale / open_active, or None on failure."""
    key = f"{repo}#{num}"
    cache = _load_outcome_cache()
    if key in cache:
        return cache[key]
    try:
        proc = subprocess.run(
            ["gh", "pr", "view", str(num), "--repo", repo,
             "--json", "state,mergedAt,closedAt,updatedAt"],
            capture_output=True, text=True, timeout=20, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    try:
        d = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return None
    if d.get("mergedAt"):
        outcome = "merged"
    elif d.get("state") == "CLOSED":
        outcome = "closed_unmerged"
    else:
        updated = d.get("updatedAt", "")
        outcome = "open_active"
        try:
            age = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(
                updated.replace("Z", "+00:00"))
            if age.days >= _STALE_DAYS:
                outcome = "open_stale"
        except (ValueError, TypeError):
            pass
    cache[key] = outcome
    _save_outcome_cache(cache)
    return outcome


def _load_outcome_cache() -> dict:
    if not OUTCOME_CACHE.exists():
        return {}
    try:
        return json.loads(OUTCOME_CACHE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_outcome_cache(d: dict) -> None:
    OUTCOME_CACHE.parent.mkdir(parents=True, exist_ok=True)
    OUTCOME_CACHE.write_text(json.dumps(d, indent=2, sort_keys=True))


def _regret_gather(history_fn, *, repo_key: str, num_key: str,
                   action_key: str, sample: int = 40):
    """Build a `gather` over the regret channel: walk recent labeled decisions,
    fetch each PR's outcome, emit an Observation for every (action, outcome)
    pair the `_SURPRISING` map flags. Capped + cached so a pass stays cheap."""
    def gather() -> list[Observation]:
        rows = history_fn()
        out: list[Observation] = []
        seen: set[tuple[str, int]] = set()
        for row in rows[:sample]:
            ctx = row.get("input", {})
            repo = ctx.get(repo_key) or row.get(repo_key)
            num = ctx.get(num_key) or row.get(num_key)
            action = str(row.get("bucket") or ctx.get(action_key) or "")
            if not repo or not num or not action:
                continue
            try:
                num = int(num)
            except (TypeError, ValueError):
                continue
            if (repo, num) in seen:
                continue
            seen.add((repo, num))
            outcome = _gh_pr_outcome(repo, num)
            if outcome is None:
                continue
            reason = _SURPRISING.get((action, outcome))
            if reason is None:
                continue
            out.append(Observation(
                signature=f"regret:{action}->{outcome}",
                detail=f"{repo}#{num}: action={action} outcome={outcome} — {reason}",
                source="regret", case=f"{repo}#{num}"))
        return out
    return gather


def _merge_gather(*gathers):
    """Compose several gather callables into one (channels are additive)."""
    def gather() -> list[Observation]:
        out: list[Observation] = []
        for g in gathers:
            out.extend(g())
        return out
    return gather


def with_outcomes(spec: SupervisorSpec, *, repo_key: str, num_key: str,
                  action_key: str) -> SupervisorSpec:
    """Return a copy of `spec` whose gather also pulls the regret channel, so a
    pass catches silent misclassifications the action/outcome corpus reveals."""
    regret = _regret_gather(spec.history, repo_key=repo_key, num_key=num_key,
                            action_key=action_key)
    return dataclasses.replace(spec, gather=_merge_gather(spec.gather, regret))


# ---------------------------------------------------------------- specs: local

SWITCH = SupervisorSpec(
    name="switch",
    goal=_GOAL,
    gather=_local_gather(
        actor_kinds={
            "switch_classifier_retry": "reason",
            "switch_classifier_failed_after_retry": "summary",
            "ghost_branch": "reason",
        },
        inbox_senders={"switch", "investigate", "reinvestigate"},
    ),
    history=_local_history(
        "switch_done", "signal",
        ("repo", "issue", "signal", "competing_pr", "summary"),
    ),
)

REMIT = SupervisorSpec(
    name="remit",
    goal=_GOAL,
    gather=_local_gather(
        actor_kinds={"remit_skipped": "reason"},
        inbox_senders={"remit"},
    ),
    history=_local_history(
        "remit_classified", "bucket",
        ("repo", "pr", "bucket", "reason", "review", "ci",
         "failing_check", "maintainer_question"),
    ),
)

COMPOSE = SupervisorSpec(
    name="compose",
    goal=_GOAL,
    gather=_local_gather(
        actor_kinds={"compose_skipped": "reason", "compose_rejected": "reason"},
        inbox_senders={"compose"},
    ),
    history=_local_history(
        "compose_done", "outcome", ("repo", "branch", "outcome", "reason"),
    ),
)


# ---------------------------------------------------------------- spec: corpus

def _gh_contributor_comments(login: str, limit: int = 40):
    """Pull a contributor's recent PR-review comments via `gh` — the public
    corpus the asymptote-learning post feeds the supervisor. Each comment is
    an Observation whose signature is the comment's coarse register (the
    deterministic shape we hope to hoist out of the `respond` nucleus)."""
    def gather() -> list[Observation]:
        try:
            proc = subprocess.run(
                ["gh", "api", "-X", "GET", "search/issues",
                 "-f", f"q=commenter:{login} type:pr", "-f", "per_page=1",
                 "--jq", ".total_count"],
                capture_output=True, text=True, timeout=30, check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return []
        # The real corpus pull walks the contributor's recent review comments.
        # gh's search API returns PRs they commented on; we fetch review
        # comments per PR and classify the register. Kept to `limit` PRs so a
        # pass stays cheap.
        out: list[Observation] = []
        try:
            prs = subprocess.run(
                ["gh", "search", "prs", f"commenter:{login}",
                 "--limit", str(limit), "--json", "repository,number"],
                capture_output=True, text=True, timeout=60, check=False,
            )
            items = json.loads(prs.stdout or "[]")
        except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
            items = []
        # The terse review register lives across THREE endpoints: review
        # bodies ("lgtm", "nit: ...", "this should be X"), inline diff comments,
        # and conversation/issue comments. Pull all three; dedup by body.
        endpoints = (
            "repos/{repo}/pulls/{num}/reviews",
            "repos/{repo}/pulls/{num}/comments",
            "repos/{repo}/issues/{num}/comments",
        )
        seen_bodies: set[str] = set()
        for it in items:
            repo = (it.get("repository") or {}).get("nameWithOwner")
            num = it.get("number")
            if not repo or not num:
                continue
            for ep in endpoints:
                try:
                    cm = subprocess.run(
                        ["gh", "api", ep.format(repo=repo, num=num), "--paginate",
                         "--jq", f'.[] | select(.user.login=="{login}") | .body'],
                        capture_output=True, text=True, timeout=30, check=False,
                    )
                except (FileNotFoundError, subprocess.TimeoutExpired):
                    continue
                for body in (cm.stdout or "").splitlines():
                    body = body.strip().strip('"')
                    if not body or body in seen_bodies:
                        continue
                    seen_bodies.add(body)
                    out.append(Observation(
                        signature=_register_signature(body),
                        detail=f"{repo}#{num}: {body}", source="corpus"))
        return out
    return gather


def _register_signature(body: str) -> str:
    """Coarse register bucket for a review comment. These are the recurring
    shapes of an expert's terse review voice — the candidates for hoisting
    `respond` from an LLM call into a templated deterministic reply."""
    b = body.lower()
    if b.startswith("nit"):
        return "register:nit"
    if "add a test" in b or "needs a test" in b or "test for" in b:
        return "register:request-test"
    if b.startswith("this should") or b.startswith("should be"):
        return "register:should-be"
    if "please" in b[:20] and ("follow" in b or "guideline" in b):
        return "register:follow-guidelines"
    if b.startswith("can you") or b.startswith("could you"):
        return "register:can-you"
    if "lgtm" in b or b.startswith("thanks"):
        return "register:approve-ack"
    return _sig_from_reason("register-other", body, n=4)


def _decisive_state(states: list[str]) -> str:
    """A reviewer may leave several reviews on one PR; collapse to the most
    decisive ACTION: a request for changes outranks an approval outranks a
    bare comment."""
    s = set(states)
    if "CHANGES_REQUESTED" in s:
        return "CHANGES_REQUESTED"
    if "APPROVED" in s:
        return "APPROVED"
    if "COMMENTED" in s:
        return "COMMENTED"
    return states[0] if states else "UNKNOWN"


def _fetch_review_actions(login: str, limit: int) -> list[dict]:
    """One network pass: for each PR `login` reviewed, pull their decisive
    review state (the ACTION) plus cheap PR features (the before-state). Shared
    by both gather and history so the corpus is fetched once."""
    try:
        prs = subprocess.run(
            ["gh", "search", "prs", f"reviewed-by:{login}",
             "--limit", str(limit), "--json", "repository,number"],
            capture_output=True, text=True, timeout=60, check=False)
        items = json.loads(prs.stdout or "[]")
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        items = []
    rows: list[dict] = []
    for it in items:
        repo = (it.get("repository") or {}).get("nameWithOwner")
        num = it.get("number")
        if not repo or not num:
            continue
        try:
            rv = subprocess.run(
                ["gh", "api", f"repos/{repo}/pulls/{num}/reviews", "--paginate",
                 "--jq", f'.[] | select(.user.login=="{login}") | .state'],
                capture_output=True, text=True, timeout=30, check=False)
            states = [s.strip() for s in (rv.stdout or "").splitlines() if s.strip()]
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        if not states:
            continue
        state = _decisive_state(states)
        try:
            pv = subprocess.run(
                ["gh", "pr", "view", str(num), "--repo", repo, "--json",
                 "additions,deletions,changedFiles,title,labels,author"],
                capture_output=True, text=True, timeout=25, check=False)
            feat = json.loads(pv.stdout or "{}")
        except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
            feat = {}
        labels = [l.get("name") for l in (feat.get("labels") or [])]
        features = {
            "additions": feat.get("additions"),
            "deletions": feat.get("deletions"),
            "changed_files": feat.get("changedFiles"),
            "labels": labels,
            "title": (feat.get("title") or "")[:120],
            "author_assoc": (feat.get("author") or {}).get("login"),
        }
        rows.append({
            "repo": repo, "num": num, "state": state, "features": features,
            "case": f"{repo}#{num}",
            "detail": (f"{repo}#{num} [+{features['additions']}/-{features['deletions']} "
                       f"{features['changed_files']}f] labels={labels} :: "
                       f"{features['title']} -> ACTION={state}"),
        })
    return rows


def review_action_spec(login: str, limit: int = 30) -> SupervisorSpec:
    """A DECISION corpus, not a comment corpus. The action is the reviewer's
    verdict (APPROVED / CHANGES_REQUESTED); the before-state is cheap PR
    features. Tests where the post-III bootstrap should actually work: is the
    expert's decision predictable from deterministic features (encodable), or
    is it judgment (agent residue)? Replay checks any proposed rule against the
    reviewer's own verdicts, blinded."""
    cache: dict[str, list[dict]] = {}

    def _rows() -> list[dict]:
        if "rows" not in cache:
            cache["rows"] = _fetch_review_actions(login, limit)
        return cache["rows"]

    def gather() -> list[Observation]:
        return [Observation(signature=f"action:{r['state']}", detail=r["detail"],
                            source="corpus", case=r["case"]) for r in _rows()]

    def history() -> list[dict]:
        return [{"input": r["features"], "bucket": r["state"]} for r in _rows()]

    return SupervisorSpec(
        name=f"actions-{login}",
        goal=(_GOAL + f" — predict {login}'s review verdict from PR features "
              "where deterministic; leave genuine judgment to the agent"),
        gather=gather, history=history)


def _author_action(ev: dict, login: str) -> str | None:
    """Classify a timeline event as one of the AUTHOR's response actions, or
    None if the event isn't the author responding."""
    et = ev.get("event")
    actor = (ev.get("actor") or {}).get("login") if isinstance(ev.get("actor"), dict) else ev.get("actor")
    user = (ev.get("user") or {}).get("login") if isinstance(ev.get("user"), dict) else None
    if et == "committed":
        # committed events carry author in .author.name/email or .actor; treat
        # any commit landing after a trigger as the author pushing a fix.
        return "push_commit"
    if et == "commented" and user == login:
        return "comment_reply"
    if et == "closed" and actor == login:
        return "close_own_pr"
    if et == "reopened" and actor == login:
        return "reopen"
    return None


def _incoming_trigger(ev: dict, login: str) -> str | None:
    """Classify a timeline event as an INCOMING state arrival the author would
    respond to (something not done by the author), or None."""
    et = ev.get("event")
    actor = (ev.get("actor") or {}).get("login") if isinstance(ev.get("actor"), dict) else ev.get("actor")
    if et == "reviewed":
        reviewer = (ev.get("user") or {}).get("login") or (ev.get("review") or {}).get("user", {}).get("login")
        state = (ev.get("state") or (ev.get("review") or {}).get("state") or "").lower()
        if reviewer and reviewer != login:
            return f"review:{state or 'commented'}"
    if et == "commented":
        commenter = (ev.get("user") or {}).get("login")
        if commenter and commenter != login:
            return "maintainer_comment"
    if et == "review_requested":
        return "review_requested"
    return None


def _fetch_author_responses(login: str, limit: int) -> list[dict]:
    """Reconstruct the author's (incoming-event -> response) trajectory from PR
    timelines. The labeled RL-classification sample: state = what landed on the
    author's open PR, action = how the author responded next."""
    try:
        prs = subprocess.run(
            ["gh", "search", "prs", f"author:{login}", "--state", "closed",
             "--limit", str(limit), "--json", "repository,number,state"],
            capture_output=True, text=True, timeout=60, check=False)
        items = json.loads(prs.stdout or "[]")
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        items = []
    rows: list[dict] = []
    for it in items:
        repo = (it.get("repository") or {}).get("nameWithOwner")
        num = it.get("number")
        if not repo or not num:
            continue
        try:
            tl = subprocess.run(
                ["gh", "api", f"repos/{repo}/issues/{num}/timeline", "--paginate",
                 "-H", "Accept: application/vnd.github.mockingbird-preview+json"],
                capture_output=True, text=True, timeout=40, check=False)
            events = json.loads(tl.stdout or "[]")
        except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
            continue
        if not isinstance(events, list):
            continue
        outcome = _gh_pr_outcome(repo, num) or "unknown"
        pending_trigger: str | None = None
        for ev in events:
            trig = _incoming_trigger(ev, login)
            if trig is not None:
                pending_trigger = trig
                continue
            act = _author_action(ev, login)
            if act is not None and pending_trigger is not None:
                rows.append({
                    "repo": repo, "num": num, "case": f"{repo}#{num}",
                    "trigger": pending_trigger, "action": act, "outcome": outcome,
                    "detail": (f"{repo}#{num}: {pending_trigger} -> {act} "
                               f"(outcome={outcome})"),
                })
                pending_trigger = None  # consume; next action needs a new trigger
    return rows


def author_response_spec(login: str, limit: int = 25) -> SupervisorSpec:
    """The AUTHOR-side response policy — exactly sweep's own respond/reinvestigate
    problem. State = incoming event on the author's open PR (changes_requested,
    maintainer comment, review_requested); action = author's response (push a
    commit, reply, close). RL-classification from expert trajectories: which
    responses are determined by the structured trigger (encodable) vs require
    reading the content (agent)?"""
    cache: dict[str, list[dict]] = {}

    def _rows() -> list[dict]:
        if "rows" not in cache:
            cache["rows"] = _fetch_author_responses(login, limit)
        return cache["rows"]

    def gather() -> list[Observation]:
        return [Observation(signature=f"{r['trigger']}->{r['action']}",
                            detail=r["detail"], source="corpus", case=r["case"])
                for r in _rows()]

    def history() -> list[dict]:
        return [{"input": {"trigger": r["trigger"], "repo": r["repo"]},
                 "bucket": r["action"]} for r in _rows()]

    return SupervisorSpec(
        name=f"respond-{login}",
        goal=(_GOAL + f" — predict how {login} responds to an incoming event on "
              "their own PR; encode the trigger-determined responses, leave "
              "content-driven ones to the agent"),
        gather=gather, history=history)


def contributor_spec(login: str) -> SupervisorSpec:
    """A corpus-bootstrap spec. History is local respond/comment decisions
    (so the idempotence wall still gates public taste against ours); if there
    are none yet, the replay gate flags proposals untested rather than
    importing a stranger's voice unchecked."""
    return SupervisorSpec(
        name=f"corpus-{login}",
        goal=_GOAL + " — and match the maintainer's terse review register",
        gather=_gh_contributor_comments(login),
        history=_local_history(
            "respond_done", "register", ("repo", "pr", "register", "summary")),
    )


SPECS = {"switch": SWITCH, "remit": REMIT, "compose": COMPOSE}

# Per-spec field names the regret channel uses to pull (repo, pr, action) out
# of each labeled-decision row. switch logs the PR number under `issue`; remit
# under `pr`. Specs absent here don't support the outcome channel.
OUTCOME_KEYS = {
    "switch": {"repo_key": "repo", "num_key": "issue", "action_key": "signal"},
    "remit": {"repo_key": "repo", "num_key": "pr", "action_key": "bucket"},
}
