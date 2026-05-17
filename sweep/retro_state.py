"""Retro pager directory — SOAP one-pagers, capped at 2.

The backward pass writes a SOAP one-pager per cycle to ~/.sweep/retros/.
Each file is human-attended: read it, decide what to act on, commit any
code changes referencing the retro's slug, then delete the file. Deletion
is the "I've Attended to this" signal — the pipeline reads the file count
as backpressure.

Cap = 2. The third concurrent file is the halt signal: forward-pass
actors check is_halted() at their takt boundary and early-return until
the human clears at least one file. Git history is the persistent record
of what was acted on; the retro file itself is ephemeral staging.

The skill that writes these files lives in ~/.claude/skills/retro/skill.md
and uses observe.events_since_cursor + observe.counters_with_prefix to
fold the cycle's data into prose. This module is the substrate the skill
writes through.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path

from sweep.io_safe import atomic_write_text


RETROS = Path.home() / ".sweep" / "retros"
RETRO_CAP = 2


# The SOAP one-pager contract. The skill renders one "round block" per
# firing; rounds accumulate in the most-recent file until that file has
# a non-empty P (prescription). Once it does, the next firing starts a
# fresh file. Empty-P rounds therefore don't burn cap slots — quiet
# stretches accumulate context without halting the pipeline.
#
# A section names codebase components (qa cascade, sift labels,
# gh_io cache, observe) — projection through the Natural Framework is
# unnecessary because the pipeline is already structurally decomposed
# by role.
FILE_HEADER = "# Retro chain — opened {slug}\n"

ROUND_TEMPLATE = """\

## Round {slug} — events {events_from}..{events_to}

### S
{subjective}

### O
{objective}

### A
{assessment}

### P
{plan}
"""


@dataclass(frozen=True)
class RetroFile:
    name: str       # filename without extension, used as the slug
    path: Path
    written_at: dt.datetime


def _retros() -> list[RetroFile]:
    if not RETROS.exists():
        return []
    out: list[RetroFile] = []
    for p in sorted(RETROS.glob("*.md")):
        try:
            mtime = dt.datetime.fromtimestamp(p.stat().st_mtime, dt.timezone.utc)
        except OSError:
            continue
        out.append(RetroFile(name=p.stem, path=p, written_at=mtime))
    return out


def list_retros() -> list[RetroFile]:
    """Every pending retro, oldest first by filename (timestamps sort)."""
    return _retros()


def is_halted() -> bool:
    """True when the pager directory holds the cap. Forward-pass actors
    early-return until at least one file is cleared."""
    return len(_retros()) >= RETRO_CAP


def slug_for_now() -> str:
    """Conventional filename body: YYYY-MM-DD-HHMM."""
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d-%H%M")


def most_recent_retro() -> RetroFile | None:
    files = _retros()
    return files[-1] if files else None


def _last_p_content(text: str) -> str:
    """Extract the body of the last `### P` section. Empty string means
    no prescriptions yet."""
    marker = "\n### P\n"
    idx = text.rfind(marker)
    if idx < 0:
        return ""
    body = text[idx + len(marker):]
    # The next "### " or "## " ends the P section if more rounds follow,
    # but since P is always the last subsection of a round, only a "## "
    # (new round) can terminate it.
    end = body.find("\n## ")
    if end >= 0:
        body = body[:end]
    return body.strip()


_EMPTY_P_RE = re.compile(
    r"^\s*[-*]?\s*[(_]*\s*(none|empty|n/?a|nothing|—|-)\s*[)_]*\s*\.?\s*$",
    re.IGNORECASE,
)


def has_prescription(retro: RetroFile) -> bool:
    """True if the file's last P section has non-whitespace content beyond
    the conventional empty-marker placeholder.

    Accepts a wide range of empty markers because LLM drafters phrase them
    inconsistently: "(none)", "- none", "_none_", "N/A", "nothing
    actionable", "—". If every non-blank line in the P body matches the
    empty pattern, treat the section as empty (append-mode next firing)."""
    try:
        text = retro.path.read_text()
    except OSError:
        return False
    body = _last_p_content(text)
    if not body:
        return False
    lines = [ln for ln in body.splitlines() if ln.strip()]
    if not lines:
        return False
    return not all(_EMPTY_P_RE.match(ln) for ln in lines)


def record_round(round_block: str, *, slug: str | None = None) -> Path:
    """The skill's main entry. Each call is one SOAP round.

    Behavior:
      - If no prior file exists, or the most-recent file already has a
        prescription, start a new file with FILE_HEADER + this round.
      - Otherwise append this round to the most-recent file (the active
        empty-P chain accumulates context until something actionable
        shows up).

    The cap is on file count, not round count. Empty-P rounds stack into
    one file and don't push the cap; only prescriptive retros consume
    slots. Raises RuntimeError if writing a new file would exceed the
    cap. Appends never raise — the active chain can always grow.
    """
    name = slug or slug_for_now()
    RETROS.mkdir(parents=True, exist_ok=True)
    recent = most_recent_retro()
    if recent is not None and not has_prescription(recent):
        # Append to the active empty-P chain. No cap pressure.
        try:
            existing = recent.path.read_text()
        except OSError:
            existing = FILE_HEADER.format(slug=recent.name)
        merged = existing.rstrip("\n") + "\n" + round_block
        atomic_write_text(recent.path, merged if merged.endswith("\n") else merged + "\n")
        return recent.path

    # Need a new file. Cap check applies here.
    if is_halted():
        raise RuntimeError(
            f"retro cap reached ({RETRO_CAP}); clear one of "
            f"{[r.name for r in _retros()]} before writing"
        )
    path = RETROS / f"{name}.md"
    content = FILE_HEADER.format(slug=name) + round_block
    atomic_write_text(path, content if content.endswith("\n") else content + "\n")
    if is_halted():
        # Local import: observe.event swallows exceptions so this is best-
        # effort. Emitted exactly when the write brings the directory to
        # the cap, so retro readers see a clean "halt fired here" marker.
        from sweep import observe
        observe.event("pipeline_halted", retro=name, cap=RETRO_CAP)
    return path


def discard_retro(name: str) -> bool:
    """Delete one retro file by slug. Returns True if removed, False if
    the file didn't exist. Deletion is the human's 'Attended' signal."""
    path = RETROS / f"{name}.md"
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False
