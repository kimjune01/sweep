# flux-rs/flux Triage Graph

Repo: https://github.com/flux-rs/flux
Stars: 855 | Language: Rust | Domain: Refinement types for Rust

## Pipeline Status

### Ready (in drip queue)

- **#858** — Do not pretty print fixpoint constraints by default
  - Labels: good first issue
  - Branch: `fix/858-fixpoint-pretty-print`
  - Status: committed, ready to push as PR
  - Change: adds compact formatting flag to ConstraintFormatter, uses compact output when communicating with fixpoint binary to reduce overhead

- **#833** — Check self type in extern spec for trait impl
  - Labels: good first issue, error-messages
  - Branch: `fix/833-extern-spec-self-type-check`
  - Status: committed, ready to push as PR
  - Change: validates that self type in extern spec matches external impl exactly, prevents `Range<usize>` when external is `Range<A>`

### Completed

- **#877** — Improve error message when type cannot be resolved
  - PR #1589: merged 2026-05-10 by nilehmann
  - Turnaround: 2 hours from PR to merge

## Candidate Issues (scored by actionability)

### Tier 1: Bug fixes with mechanical acceptance criteria

| # | Title | Labels | Actionability |
|---|-------|--------|---------------|
| 1550 | Unwrap on `None` in desugaring | — | ICE/panic, likely a missing match arm. Mechanical fix. |
| 773 | ICE: `Impossible case reached` | error-messages | ICE with repro. Defensive error handling. |
| 679 | ICE when assoc refinement used in type that doesn't implement trait | bug, error-messages | ICE with repro. Needs a guard before the panic. |

### Tier 2: Good first issues with clear scope

| # | Title | Labels | Actionability |
|---|-------|--------|---------------|
| 1381 | Update to mdbook 0.5 | good first issue | Version bump + fix CSS breakages. Needs investigation. |
| 1321 | Print summary of Flux | good first issue, enhancement | Output formatting. Scope defined by issue. |
| 1231 | Report errors for holes in unsupported positions | good first issue | Error message addition. Needs to identify positions. |

### Tier 3: Enhancements (earn trust first)

| # | Title | Labels | Notes |
|---|-------|--------|-------|
| 1583 | Add support for wildcard literals | good first issue, enhancement | Parser extension. Scope unclear. |
| 1389 | Create a `qualifier!` macro | good first issue, enhancement | Proc macro work. Medium complexity. |
| 1094 | Make `Fn` AST closer to `rustc` | good first issue | Refactoring. Scope unclear, needs discussion. |
| 1177 | Weaken type for repeated arrays | good first issue, enhancement | Type system change. Needs maintainer alignment. |

## Maintainer Preferences (from #1589, #858, #833)

- nilehmann is primary reviewer, responds within hours
- Prefers using existing rustc/stdlib methods over reimplementing
- Constructive feedback, not gatekeeping
- Clear error messages valued (multiple error-messages labeled issues)

## Competing PR Awareness

- 13 open PRs, mostly from core contributors (ninehusky, ck-* branches)
- No competing PRs for any of our target issues
- #1530 competes with #1529, #1533 competes with #1532

## Next Actions

1. Push #858 and #833 PRs via drip (both ready)
2. If both merge: target ICE fixes (#1550, #773, #679) - establish debugging skills
3. Alternatively: #1321 (print summary) - output formatting, clear spec
