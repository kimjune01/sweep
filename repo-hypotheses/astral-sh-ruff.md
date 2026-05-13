# Triage Graph: astral-sh/ruff (kimjune01)

**Scan date:** 2026-05-09
**Mode:** dry-run

## Scan Table

| # | Title | State | Score | Effort | Signal | Status |
|---|-------|-------|-------|--------|--------|--------|
| 16519 | TD003 regex — misleading error message | OPEN | 5/10 | Small (~5 lines Rust) | dylwil3 endorsed | INVESTIGATED |

## T16519: TD003 regex fix

### Root Cause

TD003 rule regex doesn't match `FOOBAR-1234` style issue refs on the same line as a TODO comment. The regex pattern in `flake8-todos` expects a specific format that excludes valid issue tracker references.

### Fix (~5 lines)

Single regex change in the TD003 rule implementation + snapshot test update.

### Prior attempts: 0/4 external PRs merged

| PR | Author | Failure mode |
|----|--------|-------------|
| #24774 | — | Multi-fix bundle, scope creep |
| #24260 | — | Closed |
| #24156 | — | Closed |
| #23101 | — | Closed |

Pattern: externals scope too broadly or bundle unrelated changes. Narrow single-file fix avoids this trap.

### PR Viability: MODERATE

**For:** dylwil3 (collaborator) endorsed the issue. Small scope. Clear bug, not design decision.
**Against:** 0/4 external success on this exact issue. 0/15 first-timer external merge rate overall. AI screening active (PR #24198 added AI policy to template). Core team (MichaReiser, charliermarsh) owns ~80% of merges.

### Competing PRs

None currently open for TD003 specifically.

### Risk

High rejection probability despite small scope. Tests H0 (size gates merge) and H6 (prior failures are scope failures) from hypothesis graph.

---

*Dry run — no remote side effects.*
