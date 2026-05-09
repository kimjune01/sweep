# RETRO_GRAPH: mvdan/sh

## Prior Art (last 15 merged PRs)

External contributor rate: **15/15** (100%). mvdan merges zero self-authored PRs in this window — pure external contributions.

Top contributors:
- kolkov (6): heavy feature work — extglob, slicing, `declare -f`, `${var@a}` — trusted power contributor
- andreynering (3): interp fixes, coreutils — repeat contributor
- kristiandueholm (2): interp panics, flag refactor — medium scope
- One-offs: vanackere, scop, risu729, feloy — small fixes/docs, all merged

Merge rate: known ~8 external merges/3mo. This window confirms that pace — kolkov alone accounts for 6.

## Pre-registration

**#813** — `BinaryNextLine` should apply to `BinaryTest` and `BinaryArithm`, not just `BinaryCmd`. Open since 2022-02. Labeled `enhancement` + `help wanted`. mvdan explicitly said "I think it would probably make sense" and left it open for community pickup.

Estimate: ~35 lines Go. Touch `syntax/printer.go` to extend the `-bn` flag logic to `BinaryTest` and `BinaryArithm` nodes. Test cases in `syntax/printer_test.go`.

## Meta-hypotheses

| ID | Hypothesis | Evidence | Classification |
|----|-----------|----------|----------------|
| H0 | Maintainer merges external PRs | 15/15 external | **Confirmed** (strongest signal across all repos) |
| H1 | Small focused PRs merge | vanackere +3/-1, scop +2/-2 merged | **Confirmed** |
| H2 | help-wanted = genuine invitation | #813 has explicit maintainer endorsement | **Confirmed** |
| H3 | Solo maintainer bottleneck | 8 merges/3mo despite 100% external — sustained | Moderate — pace is real but not fast |

## Base rates

- External merge rate: 100%
- Median external PR size: +22/-2
- Solo maintainer review latency: weeks to months (known)
- help-wanted issue age: 4+ years for #813

## Risk

Low-medium. The PR will merge if correct — mvdan merges everything external. Risk is latency: weeks of review silence is normal. The 4-year issue age is not abandonment; it is low-priority + waiting for someone to do it.
