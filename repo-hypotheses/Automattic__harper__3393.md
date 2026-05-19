# Automattic/harper#3393 — Weir `becomes` array: only first 3 alternatives reachable in tests

## Issue summary

`.weir` rule files accept an array of replacement strings via `let becomes [...]`. The runtime linter exposes all of them as suggestions, but the **test runner** only explores the first 3 via BFS, so a `test` line whose expected output uses any alternative at index ≥3 fails with `got: <first alternative>`.

## H₀ — "test runner BFS is bounded; bound is too small for arrays"

- **Hypothesis**: `WeirLinter::run_tests` does a BFS over suggestions but caps the branching factor at 3. With `becomes` arrays larger than 3, alternatives at index ≥3 are never tried.
- **Null**: the cap matches the count of explicit alternatives (i.e., array length is honored).
- **Perturbation**: read `harper-core/src/weir/mod.rs::run_tests`.
- **Trajectory**: divergent — confirmed at line 247.

```rust
// harper-core/src/weir/mod.rs:246-254
if let Some(lint) = lints.first() {
    for i in 0..3 {                              // ← hard cap, regardless of suggestions.len()
        if let Some(next) = apply_nth_suggestion(&current, lint, i)
            && seen.insert(next.clone())
        {
            queue.push_back((next, depth + 1));
        }
    }
}
```

The function name `transform_top3_to_expected` is honest: it always tries the top 3 only. That was fine when the only producer of multi-suggestion lints was a single rule auto-generating a handful of fix variants. With explicit `becomes [a, b, c, d, e, f, …]`, the test runner silently ignores items 4+.

**Status**: confirmed (deduction, 99%).

### Reproduction matched to the issue body

- Rule with `let becomes ["allegation","allegations","claim","claims","idea","rumor","rumour","rumour","rumours","story"]`
- Test expects `idea` (index 4)
- BFS explores indices 0, 1, 2 → never reaches `idea` → falls through to `transform_nth_str(text, self, 0)` which always applies suggestion 0 → reports `got: "allegation"` exactly as the user observed.

### Provenance

- `git log -S "for i in 0..3"` returns only the shallow-clone root commit (dependabot bump), so blame is unrevealing in this worktree.
- The `top3` naming is intentional cost-bounding, but it predates the `becomes`-as-array feature; the two features were never reconciled.
- No related PRs found via `gh pr list --search 'weir files'` (per context pack).

## Fix shape

Replace `0..3` with `0..lint.suggestions.len()`. The depth cap (100) and `seen` set already bound BFS cost; lifting the branching cap to `suggestions.len()` is what users expect when they explicitly list N alternatives in `becomes`.

Function renamed to `transform_to_expected` — the `top3` is no longer accurate after the cap is lifted and the new name documents the change at a glance. Two callsites, both updated.

### Regression test (fails on master, passes with fix)

Add a unit test that mirrors the issue body — a `becomes` array of 5+ items whose expected `test` output uses an alternative beyond index 2. Without the fix, the test runner returns `vec![TestResult { … }]`; with the fix, `assert_passes_all` succeeds.

## Frontier

- None remaining. Bug is single-cause, single-line.

## Reasoning modes

| Claim | Mode | Confidence |
| --- | --- | --- |
| `transform_top3_to_expected` only tries suggestion indices 0..3 | Deduction (read code) | 99% |
| User-reported failure matches this code path | Deduction (issue body matches fallback `transform_nth_str(..., 0)` exactly) | 99% |
| Lifting the cap to `suggestions.len()` does not break existing tests | Induction (`cargo test -p harper-core --lib weir` → 360/360 pass under sweep-tester) | 99% |
| Without the fix, the new regression test reproduces the user's exact `got: "allegation"` failure | Induction (reverted fix, observed `[TestResult{expected: "claims"/"idea"/"story", got: "allegation"}]`) | 99% |
