# Triage Graph: antonmedv/fx (kimjune01)

**Scan date:** 2026-05-09
**Mode:** dry-run

## Scan Table

| # | Title | State | Score | Effort | Signal | Status |
|---|-------|-------|-------|--------|--------|--------|
| 399 | Exit non-zero when reading empty files | OPEN | 6/10 | Small (~5 lines) | Bug, competing PR #402 | BLOCKED |
| 398 | SyntaxError: Invalid flags in RegExp | OPEN | 5/10 | Small-Medium | Bug, needs repro | PENDING |
| 413 | Yank doesn't work with snap | OPEN | 3/10 | Docs only | Snap environment limitation | SKIP |

## Overview

Solo maintainer (antonmedv), 7/10 external merge rate, 24h turnaround. No labels used — all issues are unlabeled. Feature requests (#410, #408, #405, #401, #400) should be avoided (maintainer is building these himself, per comments). Bug fixes are the entry point.

### Best candidates

**#399** — BLOCKED. Competing PR #402 already addresses this. Maintainer acknowledged, pending review. No action.

**#398** — RegExp SyntaxError when file path is treated as code argument. Needs reproduction steps (reporter hasn't followed up since Feb). Riskier — may be user error.

### PR Viability: GOOD

High merge rate, fast turnaround, solo maintainer. Tests H2 (standing gate) and H5 (review efficiency).

### Competing PRs

**#402** (by iyiola-dev, open 2026-03-11) fixes #399. Clean diff: 35 adds, 4 dels. Parser returns error on empty input, bounds check in `Recover()`, tests at parser and engine level. Maintainer responded 2026-04-23: "I will review! Just need to find time to do it." Stand down on #399.

### #399 Investigation Notes

- **Bug confirmed:** `printf '' | fx .` exits 0 silently on master
- **Root cause:** `Parse()` guards `skipWhitespace()` behind `p.count > 0`. On first call with empty reader, `p.eof` is already true (set during constructor's `p.next()`). Returns `io.EOF` immediately. Engine treats first-call EOF as normal stream end, returns 0.
- **PR #402 fix:** Remove count guard so whitespace is always skipped. Distinguish `p.count == 0` EOF (empty input, return error) from later EOF (normal end). Plus defensive `end > 0` bounds check in `Recover()`.
- **Issue labeled "feature"** by maintainer, which may explain deprioritization. The fix is behaviorally a bug fix (exit code consistency).

---

*Dry run — no remote side effects.*
