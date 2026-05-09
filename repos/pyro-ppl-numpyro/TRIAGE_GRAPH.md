# Triage Graph: pyro-ppl/numpyro (kimjune01)

**Scan date:** 2026-05-09
**Mode:** dry-run

## Scan Table

| # | Title | State | Score | Effort | Signal | Status |
|---|-------|-------|-------|--------|--------|--------|
| 2187 | Enhance distribution docs with math explanations | OPEN | 7/10 | Medium (docs) | good-first-issue, collaborator pinged maintainers | BRANCH_READY |
| 1872 | Support constraints.cat and CatTransform | OPEN | 5/10 | Medium-High | good-first-issue, feature | PENDING |
| 810 | Weighted statistics in summary diagnostics | OPEN | 5/10 | Medium | good-first-issue | PENDING |

## Overview

90% external merge rate (highest signal in roster). 11 labeled issues (5 help-wanted + 6 good-first-issue). fehiepsi is primary maintainer, actively engages with contributors. Tests H0 (issue-first merge rate) and H5 (review efficiency).

### Best candidate

**#2187** — Documentation enhancement with mathematical explanations. Collaborator (Qazalbash) just pinged maintainers (May 8). Good-first-issue labeled. Doc contributions have highest merge rate and build standing for future code PRs.

**#1872** — CatTransform feature. More technical but maintainer (fehiepsi) gave implementation guidance. Multiple reference implementations linked.

### PR Viability: STRONG

Highest external merge rate in roster. Maintainer actively mentors contributors. Doc PR is safest entry point.

### Competing PRs

Scanned 2026-05-09. No open PRs reference #2187 or "distribution docs". Clear to proceed.

### Branch Ready

**#2187** branch `docs-2187-distribution-math` at `/Users/junekim/Documents/numpyro`. Covers Normal, Cauchy, Exponential (3 of ~80 unchecked distributions). Follows format from merged PR #2185 (Beta/BetaProportion). 209 lines added, import-tested.

---

*Dry run — no remote side effects.*
