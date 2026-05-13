# gleam-lang/gleam Triage Graph

**Repo**: gleam-lang/gleam (21K stars, Rust+Erlang, functional programming language)
**Date**: 2026-05-09

## Issue Selection

### Scanned
- 20 good-first-issue issues
- 30+ help-wanted issues (broader scan)
- Bug label: 0 open

### Eliminated (competing PRs or claimed)
| Issue | Reason |
|-------|--------|
| #5654 | PR #5657 open (mvanhorn) |
| #5644 | PR merged by maintainer |
| #5613 | PR #5675 open (Metbcy), HIGH PRIORITY |
| #5612 | PR #5693 open (ankddev), HIGH PRIORITY |
| #5607 | PR #5610 open (13dev) |
| #5606 | PR #5609 open (ankddev) |
| #5573 | Claimed by lupodevelop |
| #5561 | PR #5595 open |
| #5543/#5544 | LSP features, no competing PRs but complex |
| #5430 | PR #5655 open (raffomania) |
| #5379 | PR #5518 open (ankddev) |
| #5363 | PR #5399 open (ankddev) |
| #5272 | PR #5276 open (giacomocavalieri, core team), HIGH PRIORITY |
| #5261 | PR #5302 open (IgorCastejon) |
| #5145 | PR #5158 open (seafoamteal) |
| #4894 | PR merged |
| #4772 | PR opened by Courtcircuits |
| #4520 | Claimed by daniellionel01 |
| #4476 | Claimed by ankddev |
| #4318 | Stale -- pre-OAuth auth system, env vars no longer relevant |
| #3972 | Claimed by ahuangg (16 months stale, feature not bug) |
| #3662 | Blocked on upstream lsp-types |
| #3143 | PR #4567 closed as stale, architectural scope |
| #3015 | Claimed by ankddev, HIGH PRIORITY |
| #2697 | Claimed by realraphrous |
| #2569 | Claimed by kfc35 |
| #2566 | Claimed by mewssix (recent) |

### Selected: #4658
**Title**: Avoid calling `bitArraySliceToFloat` in generated JS for float patterns
**Category**: Performance bug (JS code generator)
**Maintainer signal**: giacomocavalieri (core team) filed it, lpil confirmed still needed
**Competing PRs**: None (seafoamteal asked in Jan 2026, never followed up)
**Why**: Clear mechanical fix, well-scoped, no design ambiguity, no competing work

## Implementation

### Approach
When pattern matching on float segments in bit arrays, the JS code generator called `bitArraySliceToFloat` twice with identical arguments -- once for the `Number.isFinite()` check and once for the variable binding. 

Fix: cache the float read result using a FIFO queue (`VecDeque<EcoString>`) of variable names. Each `SegmentIsFiniteFloat` check declares a variable and assigns the float result to it via an assignment expression inside the condition (`Number.isFinite($ = bitArraySliceToFloat(...))`). The body binding pops from the front of the queue to reuse the cached variable.

### Trade-off
The `let $;` declaration breaks the if-condition merging optimization, adding one extra level of nesting. The duplicate `bitArraySliceToFloat` call is eliminated.

### Files changed
- `compiler-core/src/javascript/decision.rs` (core fix)
- `compiler-core/src/javascript/tests/bit_arrays.rs` (3 new tests)
- 31 snapshot files updated

### Review gates
- **Codex**: Identified single-slot cache bug (correct), led to VecDeque refactor
- **Gemini**: Rejected on branch-pollution concern (incorrect -- decision tree merging and scope save/restore handle this correctly, verified with test)
- **Tests**: 3824/3824 pass (gleam-core), pre-existing test-output failures unrelated

### Branch
`fix/deduplicate-bitarray-float-slice` on `kimjune01/gleam`
