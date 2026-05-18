"""`sweep hold-issue …` — query interface for the hold-issue holding bin.

The holding bin (`~/.sweep/hold-issue.jsonl`) is the Registry Actor
pattern: file IS the registry, no long-lived owner process. This CLI is
the read-side projection. The `file-issue` actor is the write side.

`list` — show recent filings, newest first
`show` — print one filing's record + artifact link
"""

from __future__ import annotations

import datetime as dt

import typer

from sweep import hold_issue_registry

hold_issue_app = typer.Typer(
    help="hold-issue — registry of issues the substrate filed.",
    no_args_is_help=True,
)


def _parse_since(spec: str | None):
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


@hold_issue_app.command("list")
def hold_issue_list(
    since: str = typer.Option(None, "--since", help="Window: 7d, 24h, or YYYY-MM-DD"),
    repo: str = typer.Option(None, "--repo", help="Filter to one repo"),
) -> None:
    """Filed issues, newest first."""
    cutoff = _parse_since(since)
    rows = list(reversed(hold_issue_registry.read_all()))  # newest first
    if cutoff:
        rows = [r for r in rows if dt.datetime.fromisoformat(r["ts"]) >= cutoff]
    if repo:
        rows = [r for r in rows if r.get("repo") == repo]
    if not rows:
        print("# no filings recorded")
        return
    label = f"since {since}" if since else "all time"
    print(f"# Issues filed ({label}, {len(rows)})")
    print()
    print("| when | repo#issue | source | title |")
    print("|------|-----------|--------|-------|")
    for r in rows:
        when = r.get("ts", "")[:10]
        title = (r.get("title") or "")[:60].replace("|", "\\|")
        print(f"| {when} | `{r['repo']}#{r['issue_num']}` | "
              f"`{r.get('source_investigation','-')}` | {title} |")


@hold_issue_app.command("show")
def hold_issue_show(issue_num: int = typer.Argument(...),
                    repo: str = typer.Option(None, "--repo")) -> None:
    """Print one filing's full record."""
    r = hold_issue_registry.find(issue_num, repo=repo)
    if r is None:
        print(f"_no filing recorded for #{issue_num}_")
        return
    print(f"# Filing: {r['repo']}#{r['issue_num']}")
    print(f"- url:              {r.get('url','')}")
    print(f"- title:            {r.get('title','')}")
    print(f"- when:             {r.get('ts','')}")
    print(f"- draft_id:         {r.get('draft_id','')}")
    print(f"- source:           {r.get('source_investigation','')}")
    print(f"- source_hygraph:   {r.get('source_hygraph_path','')}")
