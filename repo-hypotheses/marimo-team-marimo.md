# Triage Graph: marimo-team/marimo (kimjune01)

**Scan date:** 2026-05-09
**Mode:** dry-run

## Scan Table

| # | Title | State | Score | Effort | Signal | Status |
|---|-------|-------|-------|--------|--------|--------|
| 4153 | query_params not updating on browser navigation | OPEN | 5/10 | Medium-High (~100-200 lines) | help-wanted, maintainer WIP blueprint | INVESTIGATED |

## T4153: query_params browser navigation bug

### Root Cause

When the user navigates using browser back/forward buttons, `query_params` in marimo notebooks don't update. The reactive kernel's state reconciliation doesn't listen for `popstate` events from the browser history API. The nav/state interaction is non-trivial — marimo's cell graph needs to re-evaluate cells that depend on `query_params` when the URL changes externally.

### Fix (~100-200 lines)

Requires touching the reactive kernel's state reconciliation and the browser history API integration. Maintainer has a WIP blueprint. A blocker was resolved on main (as of last session). The fix needs to:
1. Listen for `popstate` events
2. Reconcile URL state with kernel state
3. Re-trigger dependent cells

### PR Viability: MODERATE-GOOD

**For:** 73% external merge rate (highest in roster). First-timer merges observed (stephenlf). mscolnick merges external PRs readily. help-wanted label. Maintainer acknowledged the issue.
**Against:** Open since mid-2024 — suggests genuinely hard or low-priority. ~100-200 lines is substantial. Partial fixes might stall. Reactive kernel internals are complex.

### Competing PRs

None.

### Risk

Medium. The repo is welcoming but the problem is hard. A clean, complete fix would likely merge. A partial fix risks stalling in review.

---

*Dry run — no remote side effects.*
