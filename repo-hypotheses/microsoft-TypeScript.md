# Triage Graph: microsoft/TypeScript (kimjune01)

**Scan date:** 2026-05-09
**Mode:** dry-run

## Scan Table

| # | Title | State | Score | Effort | Signal | Status |
|---|-------|-------|-------|--------|--------|--------|
| 30408 | Confusing error message for labels used before definition | OPEN | 3/10 | Medium (~50 lines) | DanielRosenwasser acknowledged | INVESTIGATED |

## T30408: Label error message — 0/7 prior attempts

### Root Cause

TS1007 error fires when a label is referenced after its definition site but the jump statement appears before the label in source order. All 7 prior PRs misdiagnosed the issue — fixing wrong error paths, changing unrelated checks, or scoping too broadly.

### Prior attempts: 0/7

| PR | Author | Closed | Failure mode |
|----|--------|--------|-------------|
| #63438 | creazyfrog | 2026-04-27 | label continue/break error |
| #63413 | Jah-yee | 2026-04-19 | invalid continue target |
| #63365 | Ankitajainkuniya | 2026-04-06 | skip block-scoped check for labels |
| #63302 | wdskuki | 2026-03-26 | label error message fix |
| #63256 | AkaHarshit | 2026-03-24 | mislabeled jump targets |
| #62925 | mhughes2012 | 2026-03-24 | string index signature fallback (wrong fix entirely) |
| #54927 | Mvmo | 2026-03-24 | out of scope label message |

Every attempt in the last 2 months failed. Pattern: misdiagnosis of which checker path to modify.

### Fix (~50 lines)

Correct path: checker label resolution in the binder/checker boundary. Must handle the case where the label identifier appears after the jump statement. ~50 lines in checker + baseline updates.

### PR Viability: WEAK

**For:** DanielRosenwasser acknowledged. If correct diagnostic path is found, it differentiates from 7 failed attempts.
**Against:** 0/7 on this exact issue over 6 years. 0/15 external behavioral merges in recent history. Core team + copilot-swe-agent own all behavioral changes. AI screening active (disclosure required, comment automation suppressed). This is functionally the hardest target in the roster.

### Competing PRs

None currently open. All 7 were closed March-April 2026.

### Risk

Very high. 0/7 base rate is the strongest signal. Value is as a hypothesis test (H0: "is this repo functionally closed to external behavioral changes?"), not as a merge candidate.

---

*Dry run — no remote side effects.*
