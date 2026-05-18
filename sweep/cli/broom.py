"""`sweep broom` — periodic file-system sweep over ~/.sweep/.

Every actor paradigm needs a broom: JSONL files grow unbounded unless
something prunes them. Default policies (per-file rationale in
sweep/broom.py); tunables under ~/.sweep/control/retain/<name>.

  sweep broom            run every policy, print per-file before/after
  sweep broom --dry-run  show what would change, touch nothing
  sweep broom <name>     run one policy, e.g. inbox/sift.jsonl
"""

from __future__ import annotations

import typer

from sweep import broom

broom_app = typer.Typer(
    help="Periodic file-system sweep over ~/.sweep/.",
    no_args_is_help=False,
    invoke_without_command=True,
)


def _fmt_bytes(n: int) -> str:
    """Short human-readable byte count. Matches the wasteboard's register."""
    for unit, scale in (("G", 1024**3), ("M", 1024**2), ("K", 1024)):
        if n >= scale:
            return f"{n/scale:.1f}{unit}"
    return f"{n}B"


def _render(results: list[broom.SweepResult], dry_run: bool) -> None:
    """One row per file: path, policy, lines before→after, bytes reclaimed.
    Quiet about files that didn't change so the eye lands on what moved."""
    if not results:
        print("(no files swept — substrate clean or empty)")
        return
    moved = [r for r in results if r.dropped > 0 or r.reclaimed_bytes > 0]
    untouched = len(results) - len(moved)
    header = "(dry-run) " if dry_run else ""
    if not moved:
        print(f"{header}all {len(results)} files clean, nothing to drop")
        return
    width = max(len(str(r.path.relative_to(broom.SWEEP_HOME))) for r in moved)
    for r in moved:
        rel = str(r.path.relative_to(broom.SWEEP_HOME))
        arrow = "→" if not dry_run else "⤳"
        print(f"  {rel:<{width}}  {r.policy:<14}  "
              f"{r.before_lines:>6} {arrow} {r.after_lines:<6} lines  "
              f"({_fmt_bytes(r.reclaimed_bytes)} reclaimed)")
    print(f"  ────────")
    total_bytes = sum(r.reclaimed_bytes for r in moved)
    total_lines = sum(r.dropped for r in moved)
    suffix = " (would reclaim)" if dry_run else " reclaimed"
    print(f"  {len(moved)} files, {total_lines} lines, {_fmt_bytes(total_bytes)}{suffix}"
          + (f"; {untouched} untouched" if untouched else ""))


@broom_app.callback()
def broom_root(
    ctx: typer.Context,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would change; touch nothing."),
) -> None:
    """Run every policy when no subcommand is given."""
    if ctx.invoked_subcommand is not None:
        return
    results = broom.sweep_all(dry_run=dry_run)
    _render(results, dry_run)


@broom_app.command("disk")
def broom_disk(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be reclaimed; touch nothing."),
) -> None:
    """Reclaim redundant disk: worktrees + build-cache for evicted repos, dangling docker >24h."""
    results = broom.disk_sweep(dry_run=dry_run)
    if not results:
        print("(no redundant disk found)")
        return
    moved = [r for r in results if r.bytes_reclaimed > 0]
    arrow = "→" if not dry_run else "⤳"
    for r in results:
        size = _fmt_bytes(r.bytes_reclaimed)
        print(f"  {r.target:<40}  {arrow} {size:>7}  ({r.reason})")
    total = sum(r.bytes_reclaimed for r in moved)
    suffix = " (would reclaim)" if dry_run else " reclaimed"
    print(f"  ────────")
    print(f"  {len(moved)} targets, {_fmt_bytes(total)}{suffix}")


@broom_app.command("one")
def broom_one(
    name: str = typer.Argument(..., help="Path under ~/.sweep/, e.g. inbox/sift.jsonl"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would change; touch nothing."),
) -> None:
    """Run one policy by file path."""
    try:
        results = broom.sweep_one(name, dry_run=dry_run)
    except (FileNotFoundError, ValueError) as e:
        raise typer.BadParameter(str(e)) from e
    _render(results, dry_run)
