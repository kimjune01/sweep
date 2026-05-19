# Hypothesis Graph: GreptimeTeam/greptimedb#7999

Issue: Region opener panicked when finding time index column during replaying
Date: 2026-05-19 (resumed; prior session 2026-05-18 was blocked on perturbation access)

## Graph State

| Node | Status | Trajectory | Summary |
| --- | --- | --- | --- |
| H0 | confirmed | divergent | `SparseReadRowHelper::new` unwraps `name_to_index.get(time_index_name)` in the non-Sparse branch (key_values.rs:341 on master). |
| H1 | confirmed | divergent | Replay caller `RegionWriteCtx::write_memtable` already filter_maps via `?` on `KeyValues::new`; extending `None` to cover missing-time-index is forward-compatible. |
| H2 | confirmed | divergent | New regression test panics on master at exactly the stack-trace site; passes with fix. Fail-on-master / pass-on-fix satisfied. |

## Causal chain

1. WAL replay feeds a `Mutation` whose `Rows.schema` lacks the region's time index column (corrupted/older-version entry, per maintainer comment).
2. `KeyValues::new` → `SparseReadRowHelper::new` (non-Sparse branch) calls `name_to_index.get(time_index_name).unwrap()` → panic.
3. Panic crashes `global-worker`, blocking region open.

## Fix

`src/mito-codec/src/key_values.rs`:
- `SparseReadRowHelper::new` returns `Option<Self>`; on missing time index, `warn!` and return `None`.
- `KeyValues::new` / `KeyValuesRef::new` propagate `None` via `?`.
- Test `test_missing_time_index_returns_none` covers the regression.

Sole production caller (`region_write_ctx.rs:237`) already uses `filter_map(|m| KeyValues::new(...)?)`, so a malformed mutation is now skipped instead of crashing — replay continues for the rest of the region.

## Provenance

- BootstrapperSBL (commenter) explicitly asked for a graceful error path here; maintainer (evenyag) said "let's keep this open."
- #8018 fixes the *write* side (verify_rows). This is the read/replay-side companion. No competing open PR.

## Verification

- Fix-side: `cargo test -p mito-codec --lib key_values::tests::test_missing_time_index_returns_none` → 1 passed.
- Master-side (test cherry-picked, production code reset): test panics with `called Option::unwrap() on a None value` at `key_values.rs:341:14` — matches the issue's exact panic.
