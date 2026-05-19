# slatedb/slatedb#1581 — Merge ops with different TTLs lost in same WriteBatch

## H₀ — Reproduce the issue from the description

- **Abduction**: Two `merge_with_options` calls on the same key in one WriteBatch, with different `Ttl::ExpireAfter`, lose one of the operands.
- **Perturbation**: read the WriteBatch write path end-to-end (`batch.rs::extract_entries` → `MergeOperatorIterator` → `mem_table.rs::put`).
- **Trajectory**: divergent confirm. The chain is:
  1. `BatchWriter::write_batch` allocates a single `commit_seq` (`oracle.next_seq()`) for the whole batch (`batch_write.rs:151`).
  2. `WriteBatch::extract_entries` constructs `WriteBatchIterator::new_with_seq_and_ttl(seq=commit_seq, ...)` so every `RowEntry` produced from the batch carries the **same `seq`** (`batch.rs:445`).
  3. The iterator is wrapped in `MergeOperatorIterator::new(merge_operator, it, /*merge_different_expire_ts=*/false, None)` (`batch.rs:363`). With `merge_different_expire_ts=false`, two `Merge` rows for the same key but distinct `expire_ts` are **not** folded — they pass through as two separate `RowEntry`s sharing `seq=commit_seq`.
  4. `WritableKVTable::put` → `KVTable::put` keys on `SequencedKey::new(row.key.clone(), row.seq)` and `compare_insert`s into a `SkipMap` (`mem_table.rs:507`). Two entries with identical `(key, seq)` collide; the second silently overwrites the first.
- **Edge generated**: the bug is the interaction between (a) one-seq-per-batch and (b) write-path TTL preservation. Either side could be the fix surface.

## H₁ — Two separate `WriteBatch`es work because seqs differ

- **Deduction**: two batches → two distinct `commit_seq`s → memtable holds both entries → read-path `MergeOperatorIterator` (`db_iter.rs:284`) is constructed with `merge_different_expire_ts=true`, folding them to `"ab"` with `min(expire_ts)=3600`.
- **Result**: confirms the author's diagnosis. The user-visible answer in the "works" case is `"ab"` with the *earlier* expiration.

## H₂ — Compare call sites of `MergeOperatorIterator::new`

| Site | `merge_different_expire_ts` | Reason |
|---|---|---|
| `batch.rs:363` (WriteBatch pre-fold) | **false** | ← BUG: entries share `seq`, will collide if not folded |
| `flush.rs:245` (memtable → L0) | false | safe: distinct seqs from memtable, preserved across flush |
| `compactor_executor.rs:319` (compaction) | false | safe: distinct seqs across SSTs |
| `db_iter.rs:287` (read path) | **true** | folds at read time |

Pattern: `false` is correct **only when entries already have distinct seqs**. The WriteBatch path is the one place where entries share a `seq`, so `false` there is the inconsistency.

## H₃ — Two minimal fix shapes

- **Fix A (one-liner)**: flip `false` → `true` in `batch.rs:363`. Two merges of `"key1"` get folded at write time into one `RowEntry` with merged value `"ab"` and `expire_ts = min(3600, 7200) = 3600`. Equal to what the read path computes for the working two-batch case, so the read-visible answer matches.
- **Fix B (larger)**: assign distinct sub-seqs to entries within a batch. Requires the oracle to reserve N seqs per batch and touches every "batch is one seq" invariant. The issue author says they have a parallel WIP that is "a larger change" — almost certainly this approach, and they explicitly want #1581 tracked as a smaller standalone fix.
- **Choice**: Fix A. Matches the read-path semantics exactly for the read-visible value, and the post-expiration story (entire merged result expires at `min(ttl)`) is a defensible reading of "merges in one batch share fate". Fix B is the maintainer's domain.

## H₄ — Provenance

- `git log` on `batch.rs`: the `merge_different_expire_ts: false` literal at line 363 predates the recent RFC-0024 segment-aware write path (be8d6e5). Not deliberate — it mirrors the flush/compactor sites without accounting for the shared-seq invariant.
- No related PR (context pack: `gh pr list --search "Merge ops"` → none).
- Issue author FiV0 is a slatedb contributor; they filed the issue and explicitly want it tracked separately from their larger WIP. No self-PR conflict.

## Frontier edges

- None open. Fix surface identified; one-line change + regression test from the issue body.

## Reasoning modes

- H₀: induction (traced code), 95%.
- H₁: deduction, 95%.
- H₂: deduction (grep + read), 99%.
- H₃: abduction + choice between two designs, 80%.
- H₄: induction (git log + context pack), 95%.

## Pruning log

- Sub-seq allocation (Fix B) pruned: reserved by issue author's parallel WIP.

## Fix

`slatedb/src/batch.rs:363` — flip `false` → `true` for `merge_different_expire_ts` in the WriteBatch pre-fold's `MergeOperatorIterator::new`. Add the issue-body test verbatim as `should_fold_batch_local_merges_across_differing_ttls` next to existing batch+merge integration tests in `slatedb/src/db.rs`.
