"""Bug-reporter — classify findings into in-scope (→ compose) vs
out-of-scope (→ file-issue).

Sister of `switch` (which classifies investigate artifacts). Any finder
(qa volley, /bug-hunt skill, leakdog, operator) can deposit a card
carrying a list of findings against a (repo, pr); bug-reporter decides
per-finding whether it's about a line the diff already touches (route
back to compose for the next round) or about adjacent code (route to
file-issue so the maintainer sees it as a separate concern, not bundled
into the active PR).

Sonnet shim does the per-finding classification. Two verdicts only
(compose / file-issue) in this first version; security-shape and
nit-shape buckets land later as growth pressure surfaces from andon /
operator override / repeated misclassification.

Hard rule from `HUMAN_ATTENTION_PRINCIPLE.md`: no silent fall-through
and no fall-back-to-human-default. Every finding routes to one of the
two real destinations, OR the activity raises an andon naming the wrong
assumption (parser failed, malformed JSON, finder format unknown).
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from dataclasses import asdict
from pathlib import Path

from temporalio import activity
from temporalio.exceptions import ApplicationError

from sweep.types import Message, forward_ledger


BUG_REPORTER_INBOX = Path.home() / ".sweep" / "inbox" / "bug-reporter.jsonl"
# Durable per-finding decision log. First-version output of the
# classifier — operator and future router actor consume this.
DECISIONS_LOG = Path.home() / ".sweep" / "inbox" / "bug-reporter-decisions.jsonl"


def _append(inbox: Path, msg: Message) -> None:
    inbox.parent.mkdir(parents=True, exist_ok=True)
    with open(inbox, "a") as f:
        f.write(json.dumps(asdict(msg)) + "\n")


async def kick_bug_reporter_card(repo: str, pr: int, *,
                                  findings: list[dict],
                                  sender: str,
                                  incoming: Message | None = None) -> str | None:
    """Deposit a bug-reporter card carrying a batch of findings.

    `findings`: list of dicts with at least `summary` (str). Optional
    fields the classifier uses when present: `file`, `line`, `severity`,
    `class`. Extra fields are passed through to the routed downstream
    card so file-issue / compose can render them.
    """
    from sweep import observe
    from sweep.activities.pr_state import _signal_actor

    if not repo or not pr or not findings:
        return None
    ts = dt.datetime.now(dt.timezone.utc)
    slug = repo.replace("/", "-")
    msg_id = f"bug-reporter-{ts.strftime('%Y%m%dT%H%M%S')}-{slug}-{pr}"
    msg = Message(
        msg_id=msg_id, sender=sender, intent="classify-findings",
        repo=repo, pr=pr, branch=None,
        payload={"findings": findings, "finder": sender},
        ts=ts.isoformat(),
        ledger=forward_ledger(incoming),
    )
    try:
        _append(BUG_REPORTER_INBOX, msg)
    except Exception as e:
        observe.event("bug_reporter_card_write_failed", repo=repo, pr=pr,
                      sender=sender, error_type=type(e).__name__,
                      error=str(e)[:200])
        return None
    observe.event("bug_reporter_card_deposited", repo=repo, pr=pr,
                  finding_count=len(findings), sender=sender, msg_id=msg_id)
    return await _signal_actor("bug-reporter", msg)


_SHIM_SYSTEM = (
    "You classify code-review findings against a pull request's diff. "
    "For each finding, decide whether it is about code the diff "
    "already modifies (`compose` — fold into the next iteration of "
    "this PR) or about adjacent code the diff does not touch "
    "(`file-issue` — surface to the maintainer as a separate concern).\n\n"
    "Bias: when uncertain, choose `file-issue`. The cost of a "
    "wrongly-routed in-scope finding is one extra issue the maintainer "
    "can close; the cost of a wrongly-routed adjacent finding is PR "
    "scope creep, which is harder to undo.\n\n"
    "Treat as `compose` only when the finding clearly references a "
    "file:line that appears in the diff's hunks, or describes behavior "
    "the diff already changes. Anything referencing untouched files, "
    "untouched functions, or `noticed-while-here` improvements goes to "
    "`file-issue`.\n\n"
    "Output ONLY a JSON object matching this shape (no markdown, no prose):\n"
    "{\n"
    '  "routes": [\n'
    '    {"idx": 0, "route": "compose|file-issue", "reason": "<one short sentence>"},\n'
    '    ...\n'
    "  ]\n"
    "}\n\n"
    "Reasons should name the load-bearing fact (e.g. \"touches "
    "src/foo.rs:42 which is in the diff\" or \"refers to src/bar.rs, "
    "not modified by this PR\"). No hedging."
)


def _fetch_diff(repo: str, pr: int) -> str:
    """Best-effort fetch of the PR's unified diff via gh. Returns the
    diff text or empty string on failure (the classifier degrades to
    reasoning from the finding text alone)."""
    r = subprocess.run(
        ["gh", "pr", "diff", str(pr), "--repo", repo],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        return ""
    return r.stdout or ""


@activity.defn
async def bug_reporter_cycle(msg: Message) -> dict:
    """Classify each finding on this card, route per verdict.

    Returns {"routes": [...]} — one entry per finding, with route
    target and downstream card id. Empty findings list is a legal noop.
    """
    from sweep import observe, pokayoke

    if not msg.repo or not msg.pr:
        raise ApplicationError(
            "bug-reporter: msg.repo and msg.pr required",
            non_retryable=True,
        )

    skip = pokayoke.bug_reporter_intake(msg)
    if skip:
        observe.event("bug_reporter_skipped", repo=msg.repo, pr=msg.pr,
                      reason=skip.code, detail=skip.detail,
                      msg_id=msg.msg_id)
        return {"status": "skipped", "reason": skip.code}

    payload = msg.payload or {}
    findings: list[dict] = payload.get("findings") or []
    if not findings:
        observe.event("bug_reporter_no_findings", repo=msg.repo, pr=msg.pr,
                      msg_id=msg.msg_id)
        return {"status": "noop", "reason": "no findings"}

    diff_text = _fetch_diff(msg.repo, int(msg.pr))
    if len(diff_text) > 40_000:
        diff_text = (diff_text[:20_000]
                     + "\n\n[... diff truncated ...]\n\n"
                     + diff_text[-20_000:])

    # Build the user prompt: diff + numbered findings.
    findings_block = "\n\n".join(
        f"Finding {i}:\n{(f.get('summary') or '').strip()}"
        + (f"\n(reported at {f.get('file')}:{f.get('line')})"
           if f.get("file") and f.get("line") is not None else "")
        for i, f in enumerate(findings)
    )
    user = (
        f"Diff:\n```\n{diff_text or '(diff unavailable)'}\n```\n\n"
        f"Findings:\n{findings_block}\n\n"
        f"Return the JSON object now."
    )

    from sweep import llm_io as _llm_io, models as _models
    result = await _llm_io.call(
        _models.resolve("sonnet"),
        system=_SHIM_SYSTEM,
        user=user,
        msg_id=msg.msg_id, repo=msg.repo, pr=msg.pr,
        max_tokens=1200, temperature=0.0,
    )
    text = (result.response or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].lstrip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        # Andon: name the wrong assumption. Operator clears once a
        # prompt patch or model swap is in place.
        raise ApplicationError(
            f"bug-reporter: sonnet returned malformed JSON: {e}; "
            f"expected={{routes: [...]}}, "
            f"got={text[:200]!r}",
            non_retryable=True,
        )

    routes = data.get("routes") or []
    if len(routes) != len(findings):
        raise ApplicationError(
            f"bug-reporter: sonnet returned {len(routes)} routes "
            f"for {len(findings)} findings; "
            f"expected len(routes) == len(findings); "
            f"raw={text[:300]!r}",
            non_retryable=True,
        )

    # First-version persistence: write each classification as a durable
    # decision row. Downstream routing (compose / file-issue) wires up
    # in a follow-up — the existing kick_compose_card and
    # kick_file_issue_card contracts don't accept ad-hoc findings, and
    # widening them is a separate seam-change. By writing decisions
    # here, the operator (and a future bug-reporter-router actor) can
    # observe what bug-reporter wants done without bug-reporter
    # pretending to control downstream actors yet.
    ts_now = dt.datetime.now(dt.timezone.utc).isoformat()
    routed: list[dict] = []
    for i, (f, r) in enumerate(zip(findings, routes)):
        route = (r.get("route") or "").strip()
        reason = (r.get("reason") or "").strip()[:300]
        if route not in ("compose", "file-issue"):
            raise ApplicationError(
                f"bug-reporter: sonnet returned unknown route {route!r}; "
                f"expected 'compose' or 'file-issue'; "
                f"finding={(f.get('summary') or '')[:120]!r}",
                non_retryable=True,
            )
        decision = {
            "ts": ts_now,
            "msg_id": msg.msg_id,
            "repo": msg.repo,
            "pr": int(msg.pr),
            "finding_idx": i,
            "finding": f,
            "route": route,
            "reason": reason,
            "finder": (msg.payload or {}).get("finder") or msg.sender,
        }
        try:
            DECISIONS_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(DECISIONS_LOG, "a") as fh:
                fh.write(json.dumps(decision) + "\n")
        except OSError as e:
            observe.event("bug_reporter_decision_write_failed",
                          repo=msg.repo, pr=msg.pr,
                          error_type=type(e).__name__, error=str(e)[:200])
        observe.event(
            "bug_reporter_classified",
            repo=msg.repo, pr=msg.pr,
            file=f.get("file"), line=f.get("line"),
            route=route, reason=reason,
            finding_summary=(f.get("summary") or "")[:160],
            msg_id=msg.msg_id,
        )
        routed.append({"finding_idx": i, "route": route, "reason": reason})

    return {"status": "done", "routes": routed,
            "finding_count": len(findings)}
