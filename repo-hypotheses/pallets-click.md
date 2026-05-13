# Triage Graph: pallets/click (kimjune01)

**Scan date:** 2026-05-09
**Mode:** dry-run

## Scan Table

| # | Title | State | Score | Effort | Signal | Status |
|---|-------|-------|-------|--------|--------|--------|
| 3362 | HelpFormatter.write_usage breaks options at hyphen | OPEN | 8/10 | Small (1 line) | Fix ready, retro-confirmed | CONFIRMED |
| 2779 | Wrong error message for multicharacter short option | OPEN | 5/10 | Small | good-first-issue label | PENDING |

## T3362: break_on_hyphens=False in wrap_text()

### Root Cause

`HelpFormatter.write_usage` uses `textwrap.wrap()` which by default breaks at hyphens. Options like `--some-option` get split across lines.

### Fix (1 line)

Add `break_on_hyphens=False` to the `wrap_text()` call. Retro data confirmed this fix.

### PR Viability: STRONG

Median review time: 0.1 hours (5 recent PRs merged in <6 minutes). Fastest review cycle in the roster. H3 testbed — validates drip pacing.

### Competing PRs

None.

## T2779: Wrong error message for multicharacter short option

Labeled good-first-issue. Not yet investigated. Queue behind #3362.

---

*Dry run — no remote side effects.*
