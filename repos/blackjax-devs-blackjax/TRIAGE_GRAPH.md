# blackjax-devs/blackjax Triage Graph

Triaged: 2026-05-09
Repo: https://github.com/blackjax-devs/blackjax
Fork: https://github.com/kimjune01/blackjax
Open PRs at triage time: 6

## Help-wanted issues (4 open)

### #278 — Add nested Rhat diagnostic [SELECTED]
- Labels: help wanted, important, diagnostics, adaptation
- Maintainer engagement: junpenglao (MEMBER) actively endorsed, linked paper section 6
- Competing PR: #752 by giladturok — stale since Oct 2024, no tests, maintainer asked for tests, never delivered
- Effort: medium (single function + tests, well-defined paper algorithm)
- Status: **implemented on branch `nested-rhat-diagnostic`**, ready to PR
- Score: 9/10 — clear acceptance criteria, maintainer wants it, competitor abandoned

### #368 — Implement Delayed Rejection HMC
- Labels: help wanted, enhancement, sampler, mcmc
- Maintainer engagement: junpenglao provided paper links and slides
- Competing PR: none
- Effort: large (novel sampler algorithm, requires paper implementation + integration + adaptation)
- Risk: giladturok (STAN team) expressed interest but hasn't submitted PR
- Score: 6/10 — high value but high effort, complex algorithm with ongoing research (DR-G-HMC paper June 2024)

### #176 — Implement Ensemble MCMC
- Labels: help wanted, sampler
- Maintainer engagement: issue opened by core team, reference implementation provided
- Competing PR: #797 by williamjameshandley — changes requested Oct 2025, stale since Nov 2025
- Effort: large (multiple ensemble methods, full test coverage needed)
- Score: 4/10 — blocked by active PR that has maintainer review feedback

### #288 — Add simulation-based inference algorithms
- Labels: help wanted, important, sampler
- Maintainer engagement: junpenglao closed as stale March 2026, then discussed bridging with sbijax
- Competing PR: none
- Effort: very large (entire SBI framework)
- Score: 2/10 — maintainer explicitly closed as stale, scope too large, sbijax bridge more appropriate

## Selection rationale

Issue #278 scored highest:
- Mechanical implementation from a published paper with exact equations
- Maintainer tagged it "important" and explicitly asked for tests on the competing PR
- Competing PR #752 abandoned for 6+ months (last commit Oct 2024)
- Low effort relative to the other options (sampler implementations)
- Bug-fix-adjacent: diagnostics are utility code, not new samplers (merges more easily per pipeline heuristics)

## Branch artifacts

| Issue | Branch | Status |
|-------|--------|--------|
| #278 | `nested-rhat-diagnostic` | committed, pushed, ready for PR |
