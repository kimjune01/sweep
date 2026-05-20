"""`sweep supervisor …` — run the encoding loop over a classifier, list and
apply its staged proposals.

The supervisor reads a target actor's attention channels (andon + operator
inbox), clusters recurring patterns, runs the four-case switch
(expert > agent > supervisor > human) via Sonnet, replay-gates the hoists,
and stages propose-only artifacts. This CLI is the standalone driver: no
worker, no metronome — `run` does one pass in-process.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from sweep.supervisor import PROPOSALS_DIR, supervise
from sweep.supervisor_specs import (SPECS, contributor_spec, review_action_spec,
                                    author_response_spec, with_outcomes,
                                    OUTCOME_KEYS)

supervisor_app = typer.Typer(
    help="Supervisor — encoding loop over classifiers (propose-only)",
    no_args_is_help=True,
)


def _resolve(name: str, limit: int | None = None):
    if name in SPECS:
        return SPECS[name]
    if name.startswith("actions-"):
        return review_action_spec(name[len("actions-"):], limit=limit or 30)
    if name.startswith("respond-"):
        return author_response_spec(name[len("respond-"):], limit=limit or 25)
    if name.startswith("corpus-"):
        return contributor_spec(name[len("corpus-"):])
    return None


@supervisor_app.command("run")
def supervisor_run(
    spec: str = typer.Argument(
        ..., help="switch | remit | compose | corpus-<login> | actions-<login> | respond-<login>"),
    verbose: bool = typer.Option(False, "--verbose", "-v",
                                 help="Print the full pass summary"),
    outcomes: bool = typer.Option(
        False, "--outcomes",
        help="Also pull the regret channel (fetch PR outcomes via gh to catch "
             "silent misclassifications). Slower — one gh call per recent "
             "decision. switch/remit only."),
    limit: int = typer.Option(
        None, "--limit",
        help="Corpus sample size for actions-/respond- specs (PRs to pull). "
             "Full-time contributors have hundreds; bump this for coverage."),
) -> None:
    """Run one supervisor pass over SPEC. Stages proposals to
    ~/.sweep/supervisor/proposals/ and HITL cards to the human inbox.
    Never edits source — propose-only."""
    s = _resolve(spec, limit=limit)
    if s is None:
        raise typer.BadParameter(
            f"unknown spec '{spec}' (have: {', '.join(SPECS)}, or corpus-<login>)")
    if outcomes:
        if spec not in OUTCOME_KEYS:
            raise typer.BadParameter(
                f"--outcomes not supported for '{spec}' (have: {', '.join(OUTCOME_KEYS)})")
        s = with_outcomes(s, **OUTCOME_KEYS[spec])
    summary = supervise(s, verbose=verbose)
    print(f"# Supervisor pass — {summary['spec']}")
    print(f"goal: {summary['goal']}")
    print(f"observations={summary['observations']}  "
          f"clusters={summary['clusters']}  "
          f"recurring={summary['recurring']}")
    print(f"  expert     (trivial hoist):   {len(summary['expert'])}")
    print(f"  supervisor (gated hoist):     {len(summary['supervisor'])}")
    print(f"  agent      (left in nucleus): {len(summary['agent'])}")
    print(f"  human      (escalated HITL):  {len(summary['human'])}")
    print(f"  replay-rejected (conflict):   {len(summary['replay_rejected'])}")
    print(f"  verifier-down (not a verdict):{len(summary.get('verifier_down', []))}")
    print(f"  cache-skipped (known reject): {len(summary['cache_skipped'])}")
    proposed = summary["expert"] + summary["supervisor"]
    if proposed:
        print("\nstaged proposals:")
        for p in proposed:
            print(f"  [{p.get('stratum', '?')}] {p['signature']}  "
                  f"({p['count']}×)  -> {p['path']}")


@supervisor_app.command("list")
def supervisor_list() -> None:
    """List staged proposals awaiting operator review."""
    if not PROPOSALS_DIR.exists():
        print(f"(none at {PROPOSALS_DIR})")
        return
    files = sorted(PROPOSALS_DIR.glob("*.md"))
    if not files:
        print(f"(none at {PROPOSALS_DIR})")
        return
    for f in files:
        head = ""
        for line in f.read_text().splitlines():
            if line.startswith("# Supervisor proposal"):
                head = line.lstrip("# ").strip()
                break
        print(f"  {f.name}  {head}")


@supervisor_app.command("show")
def supervisor_show(
    name: str = typer.Argument(..., help="proposal filename (with or without .md)"),
) -> None:
    """Print one staged proposal."""
    fn = name if name.endswith(".md") else f"{name}.md"
    path = PROPOSALS_DIR / fn
    if not path.exists():
        raise typer.BadParameter(f"no such proposal: {fn}")
    print(path.read_text())


@supervisor_app.command("archive")
def supervisor_archive(
    name: str = typer.Argument(..., help="proposal filename (with or without .md)"),
) -> None:
    """Archive a proposal after you've applied or rejected it. The signal
    that you've Attended — the edit (if any) is in git history."""
    fn = name if name.endswith(".md") else f"{name}.md"
    path = PROPOSALS_DIR / fn
    if not path.exists():
        raise typer.BadParameter(f"no such proposal: {fn}")
    archive_dir = PROPOSALS_DIR / "archived"
    archive_dir.mkdir(parents=True, exist_ok=True)
    path.rename(archive_dir / fn)
    print(f"archived {fn}")
