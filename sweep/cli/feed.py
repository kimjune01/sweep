"""`sweep feed` — infeed (triage verdicts) + outfeed (external emits).

Two stacked sections, last N events of each, newest first. Gemba shape:
each row is one sample, no aggregates. Relative timestamp on every line
so the freshness reads at a glance; verdict colored so type-changes pop
on scan; outfeed events carry per-sample end-to-end latency back to the
matching triage_decision (or "—" if none in window).

Infeed: `triage_decision` events.

Outfeed: anything that lands in a maintainer's GitHub notifications.
Today that's `submit_published` (PR opened), `comment_issue_posted` (issue
comment), and `sign_posted` (PR sign-off comment). Body splices
(amend/compose) are deliberately excluded — they don't notify.

Link compaction: `repo#n [Issue](url)` / `repo#n [PR](url)` — the
identity (repo#number) scans as plain text; the bracket is just a
click target.
"""

from __future__ import annotations

import datetime as dt
import sys

import typer

from sweep import observe

INFEED_KIND = "triage_decision"
OUTFEED_KINDS = ("submit_published", "comment_issue_posted", "sign_posted")

SCAN_LIMIT = 500
# Outfeed→triage join window. If no matching triage_decision for the
# same repo+issue lands within this many events of history, we render
# the latency as "—" rather than reaching arbitrarily far back.
JOIN_SCAN_LIMIT = 5000

# ANSI color codes for verdicts. Suppressed when --plain (TUI capture)
# or when stdout isn't a TTY.
_VERDICT_COLOR = {
    "investigate": "\x1b[32m",  # green — work continues
    "surface":     "\x1b[36m",  # cyan — needs human
    "defer":       "\x1b[33m",  # yellow — come back later
    "drop":        "\x1b[90m",  # gray — dead
}
_RESET = "\x1b[0m"


def register(app: typer.Typer) -> None:
    app.command("feed")(feed)


def _parse_ts(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _relative(ts: dt.datetime | None, now: dt.datetime) -> str:
    if ts is None:
        return "?"
    delta = now - ts
    secs = int(delta.total_seconds())
    if secs < 0:
        return "0s ago"
    if secs < 60:
        return f"{secs}s ago"
    mins = secs // 60
    if mins < 60:
        return f"{mins}m ago"
    hours = mins // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


def _latency(start: dt.datetime | None, end: dt.datetime | None) -> str:
    if start is None or end is None:
        return "—"
    secs = int((end - start).total_seconds())
    if secs < 0:
        return "—"
    if secs < 60:
        return f"{secs}s"
    mins = secs // 60
    if mins < 60:
        return f"{mins}m"
    hours = mins // 60
    if hours < 24:
        return f"{hours}h"
    return f"{hours // 24}d"


def _color_verdict(decision: str, use_color: bool) -> str:
    if not use_color:
        return decision
    code = _VERDICT_COLOR.get(decision)
    return f"{code}{decision}{_RESET}" if code else decision


def _issue_anchor(repo: str, issue: int | str) -> str:
    # Bare URL form so the terminal recognizes it as cmd-clickable.
    # GitHub redirects /issues/N to /pull/N when N is a PR, so this
    # works for either shape.
    if issue == "-" or not repo or repo == "?":
        return f"`{repo}#{issue}`"
    return f"github.com/{repo}/issues/{issue}"


def _pr_anchor(repo: str, pr: int | str, url: str | None = None) -> str:
    if pr == "-" or not repo or repo == "?":
        return f"`{repo}#{pr}`"
    return f"github.com/{repo}/pull/{pr}"


def _infeed_line(ev: dict, now: dt.datetime, use_color: bool) -> str:
    repo = ev.get("repo", "?")
    issue = ev.get("issue") or ev.get("pr") or "-"
    decision = ev.get("decision", "?")
    score = ev.get("score")
    reason = (ev.get("reason") or "").strip()
    when = _relative(_parse_ts(ev.get("ts")), now)
    score_str = f" (score {score})" if score is not None else ""
    reason_str = f' — "{reason}"' if reason else ""
    verdict = _color_verdict(decision, use_color)
    return f"- `{when:>7}` {_issue_anchor(repo, issue)} {verdict}{score_str}{reason_str}"


def _outfeed_line(
    ev: dict,
    triage_index: dict[tuple[str, int | str], dt.datetime],
    now: dt.datetime,
) -> str:
    repo = ev.get("repo", "?")
    kind = ev.get("kind")
    ev_ts = _parse_ts(ev.get("ts"))
    when = _relative(ev_ts, now)
    issue_or_pr = ev.get("issue") or ev.get("pr")
    triage_ts = triage_index.get((repo, issue_or_pr)) if issue_or_pr is not None else None
    lat = _latency(triage_ts, ev_ts)
    lat_str = f" ({lat} after triage)"

    if kind == "submit_published":
        pr = ev.get("pr") or "-"
        return f"- `{when:>7}` {_pr_anchor(repo, pr)} PR opened{lat_str}"
    if kind == "comment_issue_posted":
        issue = ev.get("issue") or "-"
        return f"- `{when:>7}` {_issue_anchor(repo, issue)} comment-issue comment{lat_str}"
    if kind == "sign_posted":
        pr = ev.get("pr") or "-"
        return f"- `{when:>7}` {_pr_anchor(repo, pr)} sign-off comment{lat_str}"
    return f"- `{when:>7}` {repo} {kind}"


def _build_triage_index(events: list[dict]) -> dict[tuple[str, int | str], dt.datetime]:
    """Most-recent triage_decision timestamp per (repo, issue). Events
    arrive newest-first; first sighting wins."""
    out: dict[tuple[str, int | str], dt.datetime] = {}
    for ev in events:
        if ev.get("kind") != INFEED_KIND:
            continue
        repo = ev.get("repo")
        issue = ev.get("issue") or ev.get("pr")
        if not repo or issue is None:
            continue
        key = (repo, issue)
        if key in out:
            continue
        ts = _parse_ts(ev.get("ts"))
        if ts is not None:
            out[key] = ts
    return out


def feed(
    limit: int = typer.Option(10, "--limit", "-n", help="How many of each section"),
    plain: bool = typer.Option(False, "--plain", help="Suppress ANSI color (TUI capture)"),
) -> None:
    """Infeed (triage verdicts) + outfeed (external emits). Newest first."""
    use_color = not plain and sys.stdout.isatty()
    now = dt.datetime.now(dt.timezone.utc)

    infeed = observe.events_recent(limit=SCAN_LIMIT, kind=INFEED_KIND)[:limit]

    # One scan covers both outfeed slicing and the triage join index.
    history = observe.events_recent(limit=JOIN_SCAN_LIMIT)
    triage_index = _build_triage_index(history)
    outfeed: list[dict] = []
    for ev in history:
        if ev.get("kind") in OUTFEED_KINDS:
            outfeed.append(ev)
        if len(outfeed) >= limit:
            break

    print(f"# Feed (last {limit} of each)")
    print()
    print("## Infeed")
    if not infeed:
        print("_no triage verdicts recorded_")
    else:
        for ev in infeed:
            print(_infeed_line(ev, now, use_color))
    print()
    print("## Outfeed")
    if not outfeed:
        print("_no external emits recorded_")
    else:
        for ev in outfeed:
            print(_outfeed_line(ev, triage_index, now))
