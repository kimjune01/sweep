# RETRO_GRAPH: marimo-team/marimo

## Prior Art (last 15 merged PRs)

External contributor rate: **11/15** (73%). mscolnick merges external PRs readily.
- kirangadhave (7): core refactors, transactions, autosave — trusted collaborator cadence
- Light2Dark (2): AI/pydantic, docs — medium-scope features accepted
- stephenlf (1): bug fix +70/-10 — external fix merged clean
- dmadisetti (1): release cut — release process is shared

mscolnick self-merges tests and fixes. External PRs range from 1-line to 320-line refactors.

## Pre-registration

**#4153** — `query_params` not updating on browser nav. Open, labeled `bug` + `help wanted`. Medium scope. This is a maintainer-acknowledged WIP blueprint — the nav/state interaction is non-trivial. A fix would need to touch the reactive kernel's state reconciliation.

Estimate: ~100-200 lines, requires understanding marimo's reactive cell graph and browser history API integration.

## Meta-hypotheses

| ID | Hypothesis | Evidence | Classification |
|----|-----------|----------|----------------|
| H0 | Maintainer merges external PRs | 11/15 external | **Confirmed** |
| H1 | Small fixes merge faster than features | stephenlf fix merged; Light2Dark feature merged same window | Neutral |
| H2 | help-wanted label signals real willingness | #4153 open 1yr+, still labeled | Weak signal — label ≠ urgency |
| H3 | Trusted collaborators get fast merge | kirangadhave: 7 in one window | **Confirmed** for repeat contributors |

## Base rates

- External merge rate: 73% (high)
- Median external PR size: +56/-5 (modest)
- First-time contributor merge: observable (stephenlf)
- Time-to-merge for help-wanted: unknown, #4153 still open

## Risk

Medium. The repo merges external work, but #4153 has been open since mid-2024. Suggests the problem is genuinely hard or low-priority. A PR that solves it cleanly would likely merge; a partial fix might stall.
