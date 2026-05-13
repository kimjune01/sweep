# pola-rs/polars Triage Graph

Triaged: 2026-05-09
Repo: 38K stars, Rust+Python dataframe library, daily external merges

## Selected: #27284 (qcut empty include_breaks)

- **Issue**: qcut with include_breaks=True returns Categorical instead of Struct on empty Series
- **Status**: Accepted, P-low, bug
- **Competing PRs**: 0 (HoraDomu claimed 3 weeks ago, no PR submitted)
- **Root cause**: Early return in `crates/polars-ops/src/series/ops/cut.rs` line 187-194 always returns `DataType::from_categories(Categories::global())` regardless of `include_breaks`. When series is empty (len=0), `null_count() == len()` is true (0==0).
- **Fix**: Return `StructChunked` with breakpoint (Float64) + category (Categorical) fields when `include_breaks=true` in the early-return path.
- **Branch**: `fix/qcut-empty-include-breaks`
- **Commit**: a868fec53e
- **Tests**: 3 new tests in `py-polars/tests/unit/operations/test_qcut.py` covering empty series, empty series in lazy context, and all-null series with include_breaks.

## Rejected

### #26290 — scan_delta file skip predicate not working for bool dtype
- Lead issue from task. Collaborator-filed.
- **Dead**: toreerdmann has open PR #27452. Maintainer approved submission.

### #21898 — pl.datetime needs a way to fail silently
- **Dead**: PR #27463 already open by jonathansergio.

### #12868 — next() on GroupBy raises AttributeError
- **Dead**: 3 open PRs (#27324, #27349, #16499). Extremely crowded.

### #19266 — Add include_file_paths to read_csv
- **Dead**: 2 open PRs (#24440, #19314).

### #12862 — .list.product
- Likely obsolete due to #22650 (Expr.list.agg). Last comments suggest this.
- Previous PRs closed without merge.

### #2994 — ODBC reader/writers
- Ancient (2021), no activity, likely stale.

### #27004 — Env var panic on import
- **Dead**: FHTMitchell working on fix, maintainer orlp confirmed.

### #26465 — LazyFrame SQL serialization
- Maintainer ritchie46 says needs IR refactoring first. Too architectural.
- richardhapb claimed it.

### #27155 — hist panic with String
- Closed PR #27228 just converted unwrap to ?. Maintainer says not trivial.
- Has related issues. Risky for first contribution.

### #26843 — pivot panic with fill_null
- **Dead**: PR #26863 already merged.

### #26723 — casting fails with untyped literal
- **Dead**: PR #27011 already merged.

### #27457 — join_asof check_sortedness streaming
- **Dead**: PR #27461 open.

## Observations

- Good-first-issue label attracts 3-5 claimants per issue. Most never submit PRs.
- Accepted bugs without good-first-issue label have lower competition.
- Bug fixes merge (confirmed by pipeline heuristic). Features at cold repos don't.
- Polars uses conventional commits: `fix(rust):`, `feat:`, `refactor:`, etc.
- Test file pattern: `py-polars/tests/unit/operations/test_*.py`
