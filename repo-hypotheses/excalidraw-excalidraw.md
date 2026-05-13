# Triage Graph: excalidraw/excalidraw (kimjune01)

**Scan date:** 2026-05-09
**Mode:** dry-run

## Scan Table

| # | Title | State | Score | Effort | Signal | Status |
|---|-------|-------|-------|--------|--------|--------|
| 9527 | Display error for invalid hex color codes | OPEN | 6/10 | Small | good-first-issue, UX | ABORT — 18 competing PRs, 0 reviews |
| 9503 | Canvas search results unstable | OPEN | 6/10 | Small-Medium | good-first-issue, bug | PENDING |
| 9541 | Notify user when no shape tool is active | OPEN | 5/10 | Small | good-first-issue, UX | PENDING |
| 9281 | Ctrl+S opens browser save-as instead of .excalidraw | OPEN | 5/10 | Small | good-first-issue | PENDING |

## Overview

TS application (not devtool), 30% external merge rate, active review. 34 labeled issues (4 help-wanted + 30 good-first-issue). Tests H1 (review schema conformance predicts merge outcome). Large codebase but good-first-issues are well-scoped.

### Best candidates

~~**#9527**~~ — **ABORT.** 18 open PRs over 12 months, zero maintainer reviews on any. Maintainer ryan-di acknowledged the issue May 2025, said "there's already a PR," then never reviewed any of the 21 total submissions. Textbook AI-friendly flood: `good-first-issue` label attracted mass submissions that saturated the review queue. Adding PR #19 is pure noise.

**#9503** — Search results jump around unstably. Likely a sorting/debounce issue. Small-medium fix. **Check competing PRs before proceeding.**

### PR Viability: MODERATE (downgraded for #9527)

30% external merge rate. Active review process. But good-first-issue pool is a trap — high label count correlates with high competing PR density. Must check competitors before any implementation.

### Competing PR Analysis (#9527)

| Metric | Value |
|--------|-------|
| Open competing PRs | 18 |
| Closed (no merge) | 3 |
| Total submissions | 21 |
| Maintainer reviews | 0 |
| Oldest open PR age | 12 months (#9576, May 2025) |
| AI-generated PRs | at least 2 (#9532 bot, #10971 KryptosAI/codex) |

### Lesson

This validates the **AI-friendly flood** heuristic: welcoming policies + `good-first-issue` label increase PR supply faster than review bandwidth. The issue is not hard — it's unreviewed. Competing PR density, not policy friendliness, predicts merge probability.

---

*Dry run — no remote side effects. #9527 removed from pipeline. Remaining candidates need competing PR checks.*
