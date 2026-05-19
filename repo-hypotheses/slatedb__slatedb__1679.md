# slatedb/slatedb#1679 — Manual flush can produce L0 SST larger than object-store single-PUT limit

## Context
- Issue: `db.flush()` of a large WriteBatch produces a single L0 SST blob; upload uses single PUT; Ceph RGW rejects with `EntityTooLarge` at >5GiB.
- Maintainer (criccomini) on 2026-05-18: "L0 writes are incorrectly using `write_sst`, which is a single PUT. These writes should be using `BufWriter` (probably through `EncodedSsTableBuilder`)."
- Reporter acknowledges that multipart "would address the immediate `EntityTooLarge` failure" but "would not fully address the SST sizing issue." Splitting the SST size is out of scope for this PR; the multipart fix is the bug fix.

## H₀ — write_sst uses single PUT regardless of size
- **Perturbation**: `grep "write_sst_in_object_store" slatedb/src/tablestore.rs`.
- **Result**: line 745–765 — `object_store.put_opts(path, data, PutMode::Create)` for the entire SST blob. No multipart, no size guard.
- **Trajectory**: divergent confirm. The bug is exactly what the maintainer described.

## H₁ — multipart via `object_store::buffered::BufWriter` is already wired for compaction output
- **Perturbation**: search for `BufWriter::new` and `table_writer`.
- **Result**: `TableStore::table_writer` (tablestore.rs:176) constructs a `BufWriter` and is used by `EncodedSsTableWriter` (compactor + tests). object_store crate version 0.12.5 — its `BufWriter` does multipart when content exceeds capacity (default 10MiB), single PUT below.
- **Trajectory**: divergent confirm. The streaming primitive exists; flush just doesn't use it.

## H₂ — WAL writes need single PUT (put-if-absent fencing); only Compacted IDs should switch
- **Perturbation**: read `write_sst_in_object_store` error handling.
- **Result** (tablestore.rs:754–762): on `AlreadyExists`, WAL maps to `SlateDBError::Fenced`; Compacted propagates as generic error. The PutMode::Create (put-if-absent) is the fencing mechanism for WAL slot writes. Multipart uploads don't support put-if-absent atomically across all backends.
- **Trajectory**: divergent. The fix must branch on id type — WAL stays single-PUT, Compacted switches to BufWriter.

## Diagnosis
For Compacted SSTs (L0 flush output + compactor output), stream the encoded bytes through `BufWriter` so multipart upload kicks in for blobs over the buffer threshold. For WAL SSTs, keep the existing single-PUT path so put-if-absent fencing semantics are preserved.

## Fix shape
- `tablestore.rs::write_sst_in_object_store`: branch on `SsTableId`. For `Compacted`, write all `unconsumed_blocks` + `footer` via `BufWriter::write_all` then `shutdown()`. For `Wal`, keep `put_opts(PutMode::Create)`.
- Iterate the existing `EncodedSsTable.unconsumed_blocks` directly so the retry model (build once, upload many) stays intact — no refactor of the build path.

## Test
`tablestore_uploads_large_compacted_sst_via_multipart`: wrap `InMemory` with a guard that rejects single-PUT payloads above a small threshold. Build an `EncodedSsTable` whose total bytes exceed the threshold. `write_sst(Compacted, …)` must succeed; the same payload via `write_sst(Wal, …)` must fail (proves the WAL path still uses single PUT).

## Provenance
- `git blame` on `write_sst_in_object_store`: unchanged single-PUT design since the table store was first introduced — not a regression, a latent bug. The configurable upload size never existed.
- No competing open PR (`gh pr list --search "Manual flush"` returned none in context pack).
- Out-of-scope, noted for follow-up: bounding L0 SST size (split memtable into multiple SSTs at flush time). Reporter explicitly called this out; maintainer comment focused on the single-PUT bug, not the sizing question.

## Frontier
- Open: should the compactor output path also be switched? `compactor_executor::write_sst` already uses `table_writer()` (streaming) for its main path, but the test helper uses `write_sst` directly. Switching all Compacted uploads via `write_sst` to multipart is consistent and safe.
- Open: should `BufWriter` capacity be tunable? Default 10MiB is fine for now; tunability is a separate config concern.

## Attestation (2026-05-18)
- **fail-on-master**: applied test slice only onto branch tip (no production diff); `cargo test write_sst_uses_buf_writer_for_compacted_and_create_for_wal` → FAILED with `assertion left == right failed: WAL upload should be the only Create-mode PUT, got [Create, Create]`. The Compacted upload goes via `PutMode::Create` on master, as predicted.
- **pass-on-fix**: with the full diff (production + test), same test → PASSED.
- Env: `docker:sweep-tester:latest` (matches qa's gate).
