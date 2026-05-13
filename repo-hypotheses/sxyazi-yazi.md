# sxyazi/yazi Triage Graph

**Repo:** sxyazi/yazi (37K stars, Rust TUI file manager)
**Maintainer:** sxyazi (solo, active, merges external PRs occasionally)
**Date:** 2026-05-09

## Merge Culture

- Solo maintainer (sxyazi) authors ~90% of merged PRs
- External merges: rare but real (immanuwell #3946, yadokani389 #3912, winlaic #3890, boydaihungst)
- Gate: CHANGES_REQUESTED on several open external PRs — maintainer is selective
- Bug fixes merge more readily than features (pattern: #3946 fix merged same day)
- Feature PRs stall for months (oldest open: #969 from 2024-04)

## Open Issues Scanned

### Bug-labeled (2)

| # | Title | Score | Action |
|---|-------|-------|--------|
| 3947 | Double-width char border corruption | **9/10** | **CLAIMED** — fix implemented, 3 review rounds, ready to PR |
| 2500 | NFS file watching not updating | 3/10 | Skip — requires NFS test env, maintainer acknowledged cause but can't test |

### Unlabeled potential bugs (0)

All other open issues are feature-labeled. No unlabeled bugs found.

## Competing PRs

- No competing PRs for #3947 (0 comments, 0 linked PRs)
- #2262 (evpeople) targets #1974 but is unrelated to our target

## Selected: Issue #3947

**Why this issue:**
1. Fresh (1 day old), maintainer-labeled as bug immediately
2. Zero comments, zero competing PRs — no collision risk
3. Rendering fix — mechanical, testable, no architectural change
4. Matches merge culture: bug fixes from externals do land (see #3946)
5. Small diff (1 file, ~10 lines) — minimal review burden

**Fix summary:**
- File: `yazi-widgets/src/clear.rs`
- Root cause: ratatui's `Clear` widget resets cells inside the area but doesn't handle double-width characters whose first cell sits just outside the left boundary. The terminal renders the wide char over the border.
- Fix: Before clearing, scan the column at `area.x - 1` for wide symbols (via `UnicodeWidthStr`) and reset them.
- Bounds: checks against `buf.area.x` (not hardcoded 0)

**Review trail:**
1. Initial implementation — compiled clean
2. Codex (GPT-5.5): flagged right-edge, bounds check, UnicodeWidthChar preference. Right-edge analysis: not needed (ratatui stores wide symbol in first cell only; right edge has no straddling problem). Applied bounds check fix.
3. Gemini (2.5 Pro): contradicted codex on UnicodeWidthChar — VS16 grapheme clusters need UnicodeWidthStr on the full symbol string. Applied.

**Branch:** `fix/double-width-border-overlap` (3 commits)
**Drip queue:** `~/.sweep/drip-queue/sxyazi-yazi.jsonl`

## Hypothesis Graph

```
H0: yazi merges external bug-fix PRs → SUPPORTED (evidence: #3946, #3912)
H1: #3947 is fixable without NFS/special env → CONFIRMED (rendering-only fix)
H2: UnicodeWidthStr is sufficient for boundary detection → SUPPORTED (covers CJK + VS16 + ZWJ)
H3: Right edge needs same treatment → REFUTED (ratatui cell model: wide char stored in first cell, continuation cells are reset/empty)
```
