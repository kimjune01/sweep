"""`sweep retro …` — inspect + manage the SOAP one-pager pager.

Writes are owned by the /retro skill (drafts SOAP prose by folding
events). This CLI is the human-side: list pending pagers, peek at one,
discard after Attending. Discard is the "I've Consolidated this — git
log carries the receipt" signal.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import typer

from sweep import observe, retro_params, retro_state


# Files whose changes shift pipeline behavior — when retro reads events,
# it needs the policy boundaries to attribute outcomes correctly. A PR
# routed to qa before BUCKET_ROUTING changed isn't comparable to one
# routed after; the classifier rule churn produces the same.
POLICY_PATHS = (
    "sweep/activities/pr_state.py",
    "sweep/activities/qa.py",
    "sweep/types.py",
    "sweep/models.py",
    "sweep/workflows",
    "skills",
)


retro_app = typer.Typer(help="Retro pager — SOAP one-pagers", no_args_is_help=True)


@retro_app.command("policy-changes")
def retro_policy_changes(
    since: str = typer.Option(None, "--since", help="ISO date, e.g. 2026-05-01"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON instead of human-readable"),
) -> None:
    """Git commits that touched pipeline policy in the sweep repo.

    Use this when retro-ing: any event before a commit's timestamp ran
    under the *previous* policy. Comparing "qa actor success rate this
    week" without aligning against the classifier rule changes that
    happened mid-week will mix two different systems and average them.
    """
    repo_root = Path(__file__).resolve().parents[2]
    cmd = ["git", "-C", str(repo_root), "log", "--format=%aI%x09%h%x09%s"]
    if since:
        cmd += [f"--since={since}"]
    cmd += ["--"] + list(POLICY_PATHS)
    try:
        out = subprocess.check_output(cmd, text=True)
    except subprocess.CalledProcessError as e:
        raise typer.Exit(code=1) from e
    rows = []
    for line in out.splitlines():
        if not line.strip():
            continue
        ts, sha, *subj = line.split("\t")
        rows.append({"ts": ts, "sha": sha, "subject": "\t".join(subj)})
    if json_out:
        print(json.dumps(rows, indent=2))
        return
    if not rows:
        print("no policy changes in range")
        return
    for r in rows:
        print(f"{r['ts']}  {r['sha']}  {r['subject']}")


@retro_app.command("params")
def retro_params_cmd(
    repo: str = typer.Option(..., help="owner/repo"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON (default: human)"),
    history: bool = typer.Option(False, "--history", help="Show every update, not just resolved values"),
) -> None:
    """Print per-repo retro parameters (last-value-wins per key)."""
    if history:
        rows = retro_params.history(repo)
        if json_out:
            print(json.dumps(rows, indent=2))
        else:
            if not rows:
                print(f"# no retro params for {repo}")
            else:
                for r in rows:
                    val = json.dumps(r.get("value"))
                    print(f"  {r.get('ts')}  {r.get('key')} = {val}")
                    print(f"      reason: {r.get('reason', '')}")
        return
    resolved = retro_params.resolved(repo)
    if json_out:
        print(json.dumps(resolved, indent=2))
    else:
        if not resolved:
            print(f"# no retro params for {repo}")
            return
        for k, v in sorted(resolved.items()):
            print(f"  {k} = {json.dumps(v)}")


@retro_app.command("set")
def retro_set(
    repo: str = typer.Option(..., help="owner/repo"),
    key: str = typer.Option(..., help="param key (e.g. merge_rate, cooldown_until)"),
    value: str = typer.Option(..., help="param value — parsed as JSON if possible, else string"),
    reason: str = typer.Option(..., help="one-line reason for the update"),
) -> None:
    """Append a parameter update to the repo's retro params file."""
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        parsed = value  # plain string
    entry = retro_params.append(repo, key=key, value=parsed, reason=reason)
    print(json.dumps(entry, separators=(",", ":")))


@retro_app.command("list")
def retro_list() -> None:
    """Pending pagers, oldest first. Cap is 2; pipeline halts at the cap."""
    files = retro_state.list_retros()
    if not files:
        print("# no pending retros")
        return
    for r in files:
        print(f"{r.written_at.isoformat(timespec='seconds')}  {r.name}")
    if retro_state.is_halted():
        print(f"\n# PIPELINE HALTED — cap {retro_state.RETRO_CAP} reached. "
              f"Discard one to resume.")


@retro_app.command("status")
def retro_status() -> None:
    """One-line summary: count + halt state."""
    n = len(retro_state.list_retros())
    state = "HALTED" if retro_state.is_halted() else "running"
    print(f"retros: {n}/{retro_state.RETRO_CAP}  pipeline: {state}")


@retro_app.command("show")
def retro_show(slug: str = typer.Argument(..., help="retro slug (filename without .md)")) -> None:
    """Print one retro to stdout."""
    path = retro_state.RETROS / f"{slug}.md"
    if not path.exists():
        raise typer.BadParameter(f"no such retro: {slug}")
    print(path.read_text())


@retro_app.command("discard")
def retro_discard(slug: str = typer.Argument(..., help="retro slug (filename without .md)")) -> None:
    """Delete one retro by slug. The signal to the pipeline that you've
    Attended — any actions worth taking should already be in git history."""
    ok = retro_state.discard_retro(slug)
    if not ok:
        raise typer.BadParameter(f"no such retro: {slug}")
    print(f"discarded {slug}")
    if not retro_state.is_halted():
        n = len(retro_state.list_retros())
        print(f"pipeline running ({n}/{retro_state.RETRO_CAP})")


@retro_app.command("record")
def retro_record(
    subjective: str = typer.Option(..., "--subjective", "-s",
                                    help="S — what the system said (events)"),
    objective: str = typer.Option(..., "--objective", "-o",
                                   help="O — what the counters/derivations show"),
    assessment: str = typer.Option(..., "--assessment", "-a",
                                    help="A — diagnosis, naming codebase components"),
    plan: str = typer.Option(..., "--plan", "-p",
                              help="P — concrete commits to make, or '(none)' for an empty-P round"),
    slug: str = typer.Option(None, "--slug",
                              help="round slug; default is YYYY-MM-DD-HHMM UTC"),
) -> None:
    """Record one SOAP round.

    Argparse enforces the SOAP shape (all four sections required). The
    substrate decides whether this round opens a new file or appends to
    the active empty-P chain. The observe cursor advances to current
    EOF on success, so the next record() reads only fresh events.

    Cap behavior: if a NEW file would push the directory past the cap,
    record refuses with exit code 1. Appending to an existing empty-P
    chain is always allowed (the backward pass must keep folding even
    under halt).
    """
    # Snapshot the events range for this round, then advance the cursor.
    events_from = observe.cursor_get()
    observe.events_since_cursor(advance=True)
    events_to = observe.cursor_get()

    block_slug = slug or retro_state.slug_for_now()
    round_block = retro_state.ROUND_TEMPLATE.format(
        slug=block_slug,
        events_from=events_from,
        events_to=events_to,
        subjective=subjective.strip(),
        objective=objective.strip(),
        assessment=assessment.strip(),
        plan=plan.strip(),
    )
    try:
        path = retro_state.record_round(round_block, slug=block_slug)
    except RuntimeError as e:
        # Cap reached. Rewind the cursor so the next attempt (after the
        # human clears a pager) sees the same events range.
        observe.cursor_set(events_from)
        raise typer.Exit(code=1) from e

    appended = (retro_state.most_recent_retro() is not None
                and path.name != f"{block_slug}.md")
    n = len(retro_state.list_retros())
    halted = " (PIPELINE HALTED)" if retro_state.is_halted() else ""
    mode = "appended to" if appended else "created"
    print(f"{mode} {path.name}  events {events_from}..{events_to}  "
          f"retros {n}/{retro_state.RETRO_CAP}{halted}")


# ── remediation prompt ──────────────────────────────────────────────
# Pattern-recognize recurring symptoms in the event stream and emit a
# bootstrap prompt per detected fix-class — a self-contained spec a
# fresh agent can execute without prior conversation context. The
# selection function ("is this fix obvious enough?") is the constraint:
# require N witness events of the same shape, the fix touches code or
# config (not policy), and blast radius is single-file. Anything
# failing those falls through to the human SOAP pager.

REMEDIATION_DIR = Path.home() / ".sweep" / "remediation-prompts"


def _recent_events(limit: int = 5000) -> list[dict]:
    path = Path.home() / ".sweep" / "events.jsonl"
    if not path.exists():
        return []
    lines = path.read_text().splitlines()[-limit:]
    out: list[dict] = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _detect_no_tests_in_pr(events: list[dict]) -> list[dict]:
    """One bootstrap prompt per (repo, pr) that hit the `no_tests_in_pr`
    verdict. Pulls from BOTH paths: routed verdicts (post-non-halt fix)
    AND legacy halt-marker reasons (transition period). Dedupes by
    (repo, msg_id)."""
    seen: dict[tuple[str, str], dict] = {}
    for e in events:
        if e.get("kind") != "attest_routed":
            continue
        text = f"{e.get('reason', '')} {e.get('verdict', '')}"
        if "no_tests_in_pr" not in text:
            continue
        msg_id = e.get("msg_id", "")
        repo = e.get("repo", "")
        seen[(repo, msg_id)] = e
    return list(seen.values())


def _detect_no_tests_from_andon() -> list[dict]:
    """Andon markers whose reason mentions `no_tests_in_pr` — captures
    halts that landed before the non-halting verdict was wired (and any
    future re-emergence of the same shape). Pulls the repo/pr from the
    marker's msg_id."""
    andon_dir = Path.home() / ".sweep" / "control" / "andon"
    if not andon_dir.exists():
        return []
    out: list[dict] = []
    for f in andon_dir.glob("*.json"):
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        reason = str(d.get("reason", ""))
        if "no_tests_in_pr" not in reason:
            continue
        msg_id = d.get("msg_id", "")
        # msg_id shape: attest-<ts>-<owner>-<repo>-<pr>
        # Extract pr (trailing integer after the last hyphen).
        pr = ""
        if "-" in msg_id:
            tail = msg_id.rsplit("-", 1)[1]
            if tail.isdigit():
                pr = tail
        # Best-effort repo extraction is brittle without ts/slug split,
        # so leave repo blank — the witness msg_id is the pointer.
        out.append({
            "msg_id": msg_id,
            "pr": pr,
            "reason": reason,
            "marker_path": str(f),
        })
    return out


# Halt reasons that get a specific bootstrap prompt elsewhere — skip
# them in the generic stale-andon detector so the same marker doesn't
# produce two prompts. New specific handlers go here.
_SPECIFIC_HALT_REASONS = ("no_tests_in_pr",)


def _detect_stale_andon_markers() -> list[dict]:
    """Andon-marker files. Each is one bootstrap prompt to reconcile
    the CLI/workflow desync. Skips markers whose reason has a more
    specific handler (write-tests, etc.) — those emit their own,
    targeted prompt."""
    andon_dir = Path.home() / ".sweep" / "control" / "andon"
    if not andon_dir.exists():
        return []
    out: list[dict] = []
    for f in andon_dir.glob("*.json"):
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        reason = str(d.get("reason", ""))
        if any(r in reason for r in _SPECIFIC_HALT_REASONS):
            continue
        out.append({"actor": d.get("actor", f.stem),
                     "msg_id": d.get("msg_id", "?"),
                     "reason": reason or "?",
                     "ts": d.get("ts", "?"),
                     "path": str(f)})
    return out


def _write_prompt(slug: str, title: str, body: str) -> Path:
    REMEDIATION_DIR.mkdir(parents=True, exist_ok=True)
    path = REMEDIATION_DIR / f"{slug}.md"
    path.write_text(f"# {title}\n\n{body}\n")
    return path


def _slug(*parts: str) -> str:
    raw = "-".join(p for p in parts if p)
    return "".join(c if c.isalnum() or c in "-_." else "-" for c in raw)


@retro_app.command("remediation-prompt")
def retro_remediation_prompt(
    limit: int = typer.Option(5000, "--limit", help="Recent event-line tail to scan"),
    dry: bool = typer.Option(False, "--dry", help="Print what would be written, don't touch disk"),
) -> None:
    """Scan recent events + substrate state for fix-class shapes that
    have an obvious remediation. Write one bootstrap prompt per match
    to ~/.sweep/remediation-prompts/<slug>.md and print pointers.

    The selection function lives in the per-pattern detectors. Adding
    a new pattern = new detector function + one branch here. Detectors
    that match nothing are silent.

    Output is a fresh-agent-runnable spec — no prior-session context
    required to execute.
    """
    events = _recent_events(limit)
    written: list[tuple[str, Path]] = []

    # Pattern 1 — no_tests_in_pr. Per witness one prompt: write a
    # regression test that fails on master and passes on this fix.
    # Pulls from both the verdict-path (non-halting; preferred shape)
    # and any straggling andon markers (legacy / transitional halts).
    no_tests_seen: set[str] = set()
    no_tests_witnesses: list[dict] = []
    for e in _detect_no_tests_in_pr(events):
        msg_id = e.get("msg_id", "?")
        if msg_id in no_tests_seen:
            continue
        no_tests_seen.add(msg_id)
        no_tests_witnesses.append({
            "repo": e.get("repo", "?"),
            "branch": e.get("branch", "?"),
            "msg_id": msg_id,
            "source": "verdict",
        })
    for m in _detect_no_tests_from_andon():
        msg_id = m.get("msg_id", "?")
        if msg_id in no_tests_seen:
            continue
        no_tests_seen.add(msg_id)
        # msg_id contains the repo slug; surface what we can.
        no_tests_witnesses.append({
            "repo": "?",
            "branch": "?",
            "msg_id": msg_id,
            "source": "andon-marker",
            "marker_path": m.get("marker_path", ""),
            "pr": m.get("pr", ""),
        })

    for w in no_tests_witnesses:
        repo = w["repo"]
        branch = w["branch"]
        msg_id = w["msg_id"]
        pr_hint = f" (PR #{w['pr']})" if w.get("pr") else ""
        slug = _slug("no-tests", repo.replace("/", "-"), msg_id[-12:])
        title = f"Write tests for {repo}{pr_hint} (branch {branch})"
        wt_path = (
            f"~/.sweep/worktrees/{repo.replace('/', '__')}/"
            if repo != "?" else "<your local checkout of the PR head>"
        )
        body = (
            f"**Symptom**: `no_tests_in_pr` verdict from attest. "
            f"Witness msg_id `{msg_id}` "
            f"(source: {w['source']}).\n\n"
            f"**Diagnosis**: PR changed files but none look like tests "
            f"(per `sweep/activities/qa.py::_looks_like_test`). The "
            f"fail-on-master/pass-on-fix gate has nothing to verify.\n\n"
            f"**Remediation** (self-contained spec):\n"
            f"1. `cd {wt_path}`\n"
            f"2. `git checkout {branch}`\n"
            f"3. Read the diff: `gh pr diff <pr> --repo {repo}`\n"
            f"4. Identify the new public behavior added by the diff. "
            f"Write a regression test under the repo's existing test "
            f"convention that exercises that behavior. The test must "
            f"fail on master (without the fix) and pass on this "
            f"branch (with the fix).\n"
            f"5. Commit + push to the same branch.\n"
            f"6. Re-attest: `sweep qa backfill --repo {repo} --pr <pr>`. "
            f"If the gate passes, the substrate writes the triple and "
            f"amends the PR body.\n"
            f"7. If a stale andon marker is present "
            f"({w.get('marker_path', '(none)')}), `sweep andon clear "
            f"attest` after the re-attest run.\n"
        )
        if dry:
            print(f"would-write: {slug}.md")
        else:
            written.append((slug, _write_prompt(slug, title, body)))

    # Pattern 2 — stale andon markers (CLI/workflow desync class).
    for m in _detect_stale_andon_markers():
        actor = m.get("actor", "?")
        slug = _slug("stale-andon", actor, m.get("msg_id", "")[-12:])
        title = f"Reconcile andon marker for {actor}"
        body = (
            f"**Symptom**: andon marker file `{m['path']}` exists.\n\n"
            f"**Diagnosis**: the marker may be stale (workflow's in-memory "
            f"`halted` is False but the file persists) OR the workflow is "
            f"genuinely halted. `sweep andon list` reads the file; "
            f"`temporal workflow query --workflow-id <actor>-actor --type "
            f"state` reads the workflow. They can diverge — the marker is "
            f"the truth for cockpit, the workflow is the truth for whether "
            f"new cards process.\n\n"
            f"**Original halt reason**: {m.get('reason', '?')}\n"
            f"**Marker timestamp**: {m.get('ts', '?')}\n\n"
            f"**Remediation**:\n"
            f"1. Query workflow state: `temporal workflow query --workflow-id "
            f"{actor.removesuffix('_cycle')}-actor --type state`.\n"
            f"2. If `halted: false`, the marker is stale — `rm "
            f"~/.sweep/control/andon/{actor}.json` and `sweep pause off`.\n"
            f"3. If `halted: true`, address the original reason (fix the "
            f"underlying issue), then `sweep andon clear {actor.removesuffix('_cycle')}`.\n"
        )
        if dry:
            print(f"would-write: {slug}.md")
        else:
            written.append((slug, _write_prompt(slug, title, body)))

    if not written and not dry:
        print("(no fix-class shapes detected in recent events)")
        return
    if not dry:
        print(f"wrote {len(written)} remediation prompt(s) to {REMEDIATION_DIR}:")
        for slug, path in written:
            print(f"  {path}")


@retro_app.command("remediation-prompt-list")
def retro_remediation_prompt_list() -> None:
    """List existing remediation prompts."""
    if not REMEDIATION_DIR.exists():
        print(f"(none at {REMEDIATION_DIR})")
        return
    files = sorted(REMEDIATION_DIR.glob("*.md"))
    if not files:
        print(f"(none at {REMEDIATION_DIR})")
        return
    for f in files:
        first_line = ""
        try:
            with open(f) as fh:
                first_line = fh.readline().strip().lstrip("# ").strip()
        except Exception:
            pass
        print(f"  {f.name}  {first_line[:80]}")


# ---------------------------------------------------------------- since helper

def _parse_since(spec: str | None):
    """Accept `Nd`, `Nh`, or ISO date (YYYY-MM-DD). Returns UTC datetime
    or None for unparseable / None input."""
    import datetime as dt
    if not spec:
        return None
    now = dt.datetime.now(dt.timezone.utc)
    s = spec.strip().lower()
    if s.endswith("h") and s[:-1].isdigit():
        return now - dt.timedelta(hours=int(s[:-1]))
    if s.endswith("d") and s[:-1].isdigit():
        return now - dt.timedelta(days=int(s[:-1]))
    try:
        return dt.datetime.fromisoformat(spec).replace(tzinfo=dt.timezone.utc)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------- missing-calls

@retro_app.command("missing-calls")
def retro_missing_calls(
    since: str = typer.Option(None, "--since", help="Window: 7d, 24h, or YYYY-MM-DD"),
    limit: int = typer.Option(20, "--limit", "-n", help="Top N by votes"),
) -> None:
    """List sweep CLI commands agents tried that don't exist. Each row is a
    wishlist entry the agent demonstrated by reaching for it."""
    from sweep import missing_calls as _mc
    entries = _mc.wishlist(since=_parse_since(since))[:limit]
    label = f"since {since}" if since else "all time"
    if not entries:
        print(f"# Missing CLI calls ({label})")
        print()
        print("_no reaches recorded_")
        return
    print(f"# Missing CLI calls ({label})")
    print()
    print("| votes | r/w | argv | latest | reason |")
    print("|------:|-----|------|--------|--------|")
    for e in entries:
        argv = " ".join(e["argv"])
        reason = (e.get("reasons") or [""])[0][:80].replace("|", "\\|")
        print(f"| {e['votes']} | r{e['reach_count']}/w{e['wish_count']} | "
              f"`{argv}` | {e['last_ts'][:10]} | {reason} |")


# ---------------------------------------------------------------- skill-stats

# event kind → (skill name, payload key whose value buckets outcomes).
# `None` outcome key means "every firing is the same bucket" — counted
# under "(fired)".
_SKILL_EVENTS: dict = {
    "triage_decision":       ("triage",        "decision"),
    "qa_converged":          ("qa",            "verdict"),
    "investigate_done":      ("investigate",   "outcome"),
    "reinvestigate_done":    ("reinvestigate", "outcome"),
    "compose_applied":       ("compose",       None),
    "amend_applied":         ("amend",         None),
    "attestation_published": ("attest",        None),
    "ping_drafted":          ("ping",          None),
    "comment_issue_posted":         ("comment-issue",        None),
    "comment_issue_skipped":        ("comment-issue",        "reason"),
    "sign_posted":           ("sign",          None),
    "sift_deposited":        ("sift",          None),
    "file_issue_drafted":    ("file-issue",    None),
    "file_issue_skipped":    ("file-issue",    "reason"),
    "issue_filed":           ("file-issue-post", None),
}


@retro_app.command("skill-stats")
def retro_skill_stats(
    since: str = typer.Option("7d", "--since", help="Window: 7d, 24h, or YYYY-MM-DD"),
) -> None:
    """Per-skill firings + outcomes within the window. Reads events.jsonl."""
    import datetime as dt
    from collections import Counter, defaultdict
    cutoff = _parse_since(since)
    if cutoff is None:
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)
    counts: dict = defaultdict(Counter)
    totals: Counter = Counter()
    for r in observe.events_recent(limit=100000):
        k = r.get("kind")
        if k not in _SKILL_EVENTS:
            continue
        try:
            ts = dt.datetime.fromisoformat(r["ts"])
        except (KeyError, ValueError, TypeError):
            continue
        if ts < cutoff:
            continue
        skill, outcome_key = _SKILL_EVENTS[k]
        totals[skill] += 1
        bucket = str(r.get(outcome_key, "-")) if outcome_key else "(fired)"
        counts[skill][bucket] += 1
    print(f"# Skill stats (since {since})")
    print()
    if not totals:
        print("_no skill firings in window_")
        return
    print("| skill | total | top outcomes |")
    print("|-------|------:|--------------|")
    for skill in sorted(totals, key=lambda s: -totals[s]):
        outcomes = ", ".join(
            f"{v}× {k}" for k, v in counts[skill].most_common(4)
        )
        print(f"| {skill} | {totals[skill]} | {outcomes} |")


# ---------------------------------------------------------------- outcomes

@retro_app.command("outcomes")
def retro_outcomes(
    repo: str = typer.Option(..., "--repo", help="owner/repo"),
    author: str = typer.Option("kimjune01", "--author",
                               help="bot/own author for the own/prior-art split"),
    limit: int = typer.Option(50, "--limit", "-n"),
) -> None:
    """PR outcomes for the repo. Own (bot-authored) + prior art (other authors),
    showing merge/close state per PR. Pulls live from gh."""
    from sweep import gh_io
    try:
        rows = gh_io.pr_list(repo, state="all", limit=limit)
    except subprocess.CalledProcessError as e:
        print(f"# Outcomes — {repo}")
        print(f"_gh failed: {(e.stderr or str(e))[:200]}_")
        return
    own: list = []
    prior: list = []
    for r in rows:
        a = (r.get("author") or {}).get("login", "")
        (own if a == author else prior).append(r)

    def _fmt(r: dict) -> str:
        n = r.get("number", "?")
        state = r.get("state", "?")
        merged = r.get("mergedAt")
        closed = r.get("closedAt")
        outcome = "merged" if merged else ("closed" if closed else state.lower())
        when = (merged or closed or r.get("updatedAt") or "")[:10]
        title = (r.get("title") or "")[:70].replace("|", "\\|")
        return f"| `{repo}#{n}` | {outcome} | {when} | {title} |"

    print(f"# Outcomes — {repo}")
    print()
    print(f"## Own ({len(own)})  author=`{author}`")
    if not own:
        print("_none_")
    else:
        print("| pr | outcome | when | title |")
        print("|----|---------|------|-------|")
        for r in own:
            print(_fmt(r))
    print()
    print(f"## Prior art ({len(prior)})")
    if not prior:
        print("_none_")
    else:
        print("| pr | outcome | when | title |")
        print("|----|---------|------|-------|")
        for r in prior:
            print(_fmt(r))


# ---------------------------------------------------------------- evict

EVICTION_PROPOSALS = Path.home() / ".sweep" / "eviction-proposals.jsonl"


@retro_app.command("evict")
def retro_evict(
    target: str = typer.Option(..., "--target", help="Name of the skill/memory/CLI to evict"),
    reason: str = typer.Option(..., "--reason", help="Why this isn't earning its keep"),
    kind: str = typer.Option("skill", "--kind", help="skill | memory | cli | other"),
) -> None:
    """Propose an eviction. Appends to ~/.sweep/eviction-proposals.jsonl
    for human review — does NOT remove anything itself."""
    import datetime as dt
    EVICTION_PROPOSALS.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "kind": kind,
        "target": target,
        "reason": reason,
    }
    with EVICTION_PROPOSALS.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"# Eviction proposal recorded")
    print(f"- kind:   {kind}")
    print(f"- target: {target}")
    print(f"- reason: {reason}")
    print(f"- log:    {EVICTION_PROPOSALS}")


# ---------------------------------------------------------------- gather

@retro_app.command("gather")
def retro_gather(
    repo: str = typer.Option(..., "--repo", help="owner/repo"),
    since: str = typer.Option("7d", "--since", help="Window: 7d, 24h, or YYYY-MM-DD"),
    jsonl: bool = typer.Option(False, "--jsonl",
                               help="Emit raw events.jsonl lines instead of markdown summary"),
) -> None:
    """All structured events for a repo since date. Default: markdown
    summary by kind. With --jsonl: raw events one per line, for piping."""
    import datetime as dt
    from collections import Counter
    cutoff = _parse_since(since)
    if cutoff is None:
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)
    matching: list = []
    for r in observe.events_recent(limit=200000):
        if r.get("repo") != repo:
            continue
        try:
            ts = dt.datetime.fromisoformat(r["ts"])
        except (KeyError, ValueError, TypeError):
            continue
        if ts < cutoff:
            continue
        matching.append(r)
    if jsonl:
        for r in matching:
            print(json.dumps(r, separators=(",", ":")))
        return
    print(f"# Gather — {repo} (since {since})")
    print()
    print(f"_{len(matching)} events_")
    if not matching:
        return
    # events_recent is newest-first, so [-1] is oldest in the window.
    first_ts = matching[-1].get("ts", "")[:19]
    last_ts = matching[0].get("ts", "")[:19]
    print(f"_window: {first_ts} → {last_ts}_")
    print()
    kind_counts = Counter(r.get("kind", "?") for r in matching)
    print("| kind | count |")
    print("|------|------:|")
    for k, v in kind_counts.most_common():
        print(f"| `{k}` | {v} |")


# ---------------------------------------------------------------- fix-ready

FIX_READY_LOG = Path.home() / ".sweep" / "fix-ready.jsonl"


@retro_app.command("fix-ready")
def retro_fix_ready(
    repo: str = typer.Option(..., "--repo"),
    issue: int = typer.Option(..., "--issue"),
    line_count: int = typer.Option(..., "--line-count", help="Diff line count of the fix"),
    description: str = typer.Option(..., "--description", help="One-line summary"),
) -> None:
    """Record a confirmed fix-ready entry. Append-only at ~/.sweep/fix-ready.jsonl.
    Used by the retro skill to mark "reproducer + fix in hand" before submission."""
    import datetime as dt
    FIX_READY_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "repo": repo,
        "issue": issue,
        "line_count": line_count,
        "description": description,
    }
    with FIX_READY_LOG.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"# fix_ready recorded")
    print(f"- repo:        {repo}")
    print(f"- issue:       #{issue}")
    print(f"- line_count:  {line_count}")
    print(f"- description: {description}")
    print(f"- log:         {FIX_READY_LOG}")


# ---------------------------------------------------------------- reclassify

@retro_app.command("reclassify")
def retro_reclassify(
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Only show what would change; don't emit events or deposit cards.",
    ),
) -> None:
    """Re-run the investigate-artifact classifier on every (repo, issue) whose
    latest investigate/reinvestigate event points to an existing hypothesis
    graph. Useful when the classifier widens or after a routing bug fix that
    silently dropped human-gated cards.

    Emits `investigate_reclassified` events for any verdict change and
    re-deposits human-inbox cards for human-gated outcomes (idempotent —
    msg_ids dedupe in the inbox view)."""
    import asyncio as _asyncio
    import datetime as _dt
    from pathlib import Path as _Path

    from sweep.activities.skill_runner import (
        _classify_investigate_artifact,
        _kick_human_decision,
    )

    # Latest investigate/reinvestigate event per (repo, issue).
    latest: dict = {}
    for r in observe.events_recent(limit=200000):
        if r.get("kind") not in ("investigate_done", "reinvestigate_done"):
            continue
        repo = r.get("repo")
        issue = r.get("issue") or r.get("pr")
        if not repo or issue is None:
            continue
        key = (repo, int(issue))
        prev = latest.get(key)
        if prev is None or r.get("ts", "") > prev.get("ts", ""):
            latest[key] = r

    if not latest:
        print("# no investigate events found")
        return

    rows: list = []  # (repo, issue, prev_signal, new_signal, summary) — changes only
    kicks: list = []  # (repo, issue, signal, summary, artifact_path) — every human-gated
    comment_kicks: list = []  # (repo, issue, signal) — comment-issue side-hatch on no-fix
    obsolete_acks: list = []  # msg_ids of human cards that should now be acked
    missing = 0
    unchanged_nonhuman = 0
    for (repo, issue), ev in latest.items():
        art = ev.get("artifact_path")
        if not art:
            continue
        path = _Path(art)
        if not path.exists():
            missing += 1
            continue
        result = _classify_investigate_artifact(path)
        if result is None:
            continue
        new_signal = result["signal"]
        prev_signal = _ev_signal(ev)
        if new_signal != prev_signal:
            rows.append((repo, issue, prev_signal, new_signal, result["summary"]))
        elif not result.get("human_gated"):
            unchanged_nonhuman += 1
        # Always re-deposit human-inbox cards for human-gated outcomes —
        # msg_id dedupes if one already exists. This is the recovery path
        # for cards lost to the Path-import bug in _kick_human_decision.
        if result.get("human_gated"):
            kicks.append((repo, issue, new_signal, result["summary"], str(path)))
        else:
            # No longer human-gated. Any pre-existing human-inbox cards
            # from prior unclassified verdicts are now obsolete; ack
            # them so the operator's inbox shrinks to reality.
            slug = repo.replace("/", "-")
            for old_sig in ("unclassified", "human-gated"):
                obsolete_acks.append(
                    f"investigate-decision-{slug}-{issue}-{old_sig}"
                )
            # No-fix verdicts with a real summary are the comment-issue
            # side-hatch trigger (parallel to investigate_cycle's
            # routing). Reclassify owns this because the verdict only
            # exists now; the original investigate_cycle ran before the
            # widened patterns matched.
            if result.get("no_fix") and result.get("summary"):
                comment_kicks.append((repo, issue, new_signal))

    print(f"# Reclassify report ({len(latest)} unique repo/issue, "
          f"{missing} missing artifacts, {unchanged_nonhuman} unchanged-non-human)")
    print()
    if rows:
        print("## Verdict changes")
        print()
        print("| repo#issue | was | now | summary |")
        print("|------------|-----|-----|---------|")
        for repo, issue, prev_sig, new_sig, summary in rows:
            s = (summary or "")[:80].replace("|", "\\|")
            print(f"| `{repo}#{issue}` | {prev_sig} | **{new_sig}** | {s} |")
        print()
    else:
        print("_no verdict changes_")
        print()

    if kicks:
        print(f"## Human-inbox cards to deposit ({len(kicks)})")
        print()
        print("_includes unchanged human-gated outcomes — recovery from "
              "the silently-dropped-card bug. msg_id dedupes if already present._")
        print()

    if dry_run:
        print(f"_dry-run: {len(rows)} verdict change(s) would be recorded; "
              f"{len(kicks)} human-inbox card(s) would be deposited_")
        return

    # Apply: emit reclassify events + re-kick human cards + ack obsolete cards.
    for repo, issue, prev_sig, new_sig, summary in rows:
        observe.event(
            "investigate_reclassified",
            repo=repo, issue=issue,
            prev_signal=prev_sig, new_signal=new_sig,
            summary=(summary or "")[:200],
        )
    deposited = 0
    if kicks:
        async def _deposit_all() -> int:
            n = 0
            for repo, issue, signal, summary, art in kicks:
                try:
                    await _kick_human_decision(
                        repo=repo, pr=int(issue),
                        signal=signal, summary=summary or "",
                        artifact_path=art,
                    )
                    n += 1
                except Exception as e:
                    observe.event(
                        "reclassify_kick_failed",
                        repo=repo, issue=issue,
                        error_type=type(e).__name__, error=str(e)[:200],
                    )
            return n
        deposited = _asyncio.run(_deposit_all())
    # comment-issue kicks: newly-no-fix verdicts route to the side-hatch.
    comment_deposited = 0
    if comment_kicks:
        from sweep.activities.comment_issue import kick_comment_issue_card
        async def _kick_comments() -> int:
            n = 0
            for repo, issue, signal in comment_kicks:
                try:
                    await kick_comment_issue_card(
                        repo=repo, issue=int(issue),
                        source="reclassify", signal=signal,
                    )
                    n += 1
                except Exception as e:
                    observe.event(
                        "reclassify_comment_kick_failed",
                        repo=repo, issue=issue,
                        error_type=type(e).__name__, error=str(e)[:200],
                    )
            return n
        comment_deposited = _asyncio.run(_kick_comments())
    # Ack obsolete cards: any human-inbox msg_id from a prior
    # classification that no longer holds. Idempotent — appending an
    # ack for a non-existent or already-acked msg_id is a no-op in
    # inbox_state's set lookup.
    acked = 0
    if obsolete_acks:
        ack_file = _Path.home() / ".sweep" / "inbox" / "_acks.jsonl"
        ack_file.parent.mkdir(parents=True, exist_ok=True)
        now_iso = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
        with ack_file.open("a") as f:
            for mid in obsolete_acks:
                f.write(json.dumps({
                    "msg_id": mid,
                    "acked_at": now_iso,
                    "by": "reclassify-obsolete",
                }) + "\n")
                acked += 1
    print()
    print(f"_applied: {len(rows)} reclassify events; "
          f"{deposited}/{len(kicks)} human cards deposited; "
          f"{comment_deposited}/{len(comment_kicks)} comment-issue cards kicked; "
          f"{acked} obsolete ack(s) written_")


def _ev_signal(ev: dict) -> str:
    """Read back the verdict bucket from an investigate_done event payload."""
    if ev.get("produced_pr"):
        return "shipped"
    if ev.get("no_fix"):
        return "no-fix"
    if ev.get("human_gated"):
        summary = ev.get("summary") or ""
        if "unclassified halt" in summary:
            return "unclassified"
        return "human-gated"
    return "(none)"
