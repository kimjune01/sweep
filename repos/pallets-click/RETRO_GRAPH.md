# Retro Graph: pallets/click

Author: kimjune01 | Period: May 9 2026 (pre-registration) | Record: 0/0 (no submissions yet)

## Own outcomes

None. This is a pre-registration document.

## Prior art

| # | Author | +/- | Result | Time to merge | Note |
|---|--------|-----|--------|---------------|------|
| 3396 | AndreasBackx | +17/-16 | **MERGED** | 3.7 days | External contributor, typing fix |
| 3372 | kdeldycke | +69/-34 | **MERGED** | 7.3 days | External, type extraction + overloads |
| 3371 | kdeldycke | +196/-109 | **MERGED** | 6.7 days | External, large typing PR |
| 3364 | kdeldycke | +75/-0 | **MERGED** | 7.7 days | External, default_map splitting |
| 3363 | kdeldycke | +113/-19 | **MERGED** | 7.7 days | External, auto-detect UNPROCESSED |
| 3343 | kdeldycke | +178/-82 | **MERGED** | 1.4 days | External, format guideline cleanup |

**Rejection pattern:** Issue #3362 (hyphen-breaking in write_usage) spawned 11 competing PRs (#3385-3413), all closed. Pattern: maintainer posts well-scoped issue, multiple contributors race to fix, most are low-effort or duplicate. None merged yet despite trivial fix (set `break_on_hyphens=False`).

**Trusted contributor:** kdeldycke has 4 merged PRs in one week. Standing earned through sustained, high-quality typing work. Review latency ~7 days for externals, <5 min for maintainer (davidism) self-merges.

## Hypothesis evidence

**H0: Issue-first > unsolicited** -- UNDETERMINED. All 6 recent merges appear driven by contributor initiative (kdeldycke's typing campaign). But #3362's 11 racing PRs show issue-first can backfire when many people pile on.

**H1: Review schema conformance** -- FOR. kdeldycke's PRs all follow consistent patterns: typed, tested, scoped. The 11 rejected write_usage PRs all failed basic quality: duplicating each other, no tests, or addressing the wrong subproblem.

**H2: Standing gates quality** -- FOR. kdeldycke ships 4 PRs in a week. A new contributor submitting the same code would face longer review. Standing = track record of mergeable work.

**H3: Drip pacing** -- UNDETERMINED (this is the testbed). Median review ~7 days. kdeldycke submitted 4 PRs in one day -- all merged within a week. Fast review cadence suggests click tolerates batching from trusted contributors. Question: does it tolerate it from unknowns?

**H5: Review efficiency** -- FOR. 11 duplicate PRs for #3362, zero merged. Maintainer cost: triaging 11 low-effort submissions. The issue remains open.

## Pre-registration

| Target | Fix | Lines | Schema |
|--------|-----|-------|--------|
| #3362 | `break_on_hyphens=False` in `write_usage` | ~1 | Issue-first, regression test |

**Prediction (H3):** Review latency ~7 days. Ship 3 PRs in a week only if drip-paced (1 per 2 days) and each is self-contained. If batch-submitted same day: first merges, rest ignored.

**Falsification:** H3 falsified if 3 same-day PRs all merge within 7 days. H1 falsified if a well-tested PR for #3362 is rejected despite conforming to kdeldycke's pattern.
