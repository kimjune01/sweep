# Hypothesis graph — pingcap/tidb#68455

**Issue.** `slice bounds out of range [8:4]` when cascades planner runs `SELECT c3 FROM idx_t2 WHERE c3 IS NOT NULL AND c6 IS NOT NULL ORDER BY c3 LIMIT 70` against a table with many indexes (incl. expression indexes). Deterministic. Disappears with `tidb_enable_cascades_planner=0`. With 50 rows, the panic shifts to `[256:128]` — exactly 2:1.

## H₀ — Bug is inside cascades planner search

- **Perturbation.** Run the issue's repro under docker (`pingcap/tidb:v8.5.6`, unistore) with cascades on and off.
- **Trajectory.** Divergent — bug reproduces under cascades, doesn't under volcano.
- **Status.** Confirmed that cascades is necessary.
- **But:** the actual panic isn't in the planner. Stack trace:

```
runtime.goPanicSliceB
chunk.(*Codec).decodeColumn        pkg/util/chunk/codec.go:145
chunk.(*Codec).DecodeToChunk
chunk.(*Decoder).Reset
distsql.(*selectResult).readFromChunk
distsql.(*selectResult).Next
executor.(*IndexReaderExecutor).Next
executor.(*LimitExec).Next
executor.(*ProjectionExec).unParallelExecute
```

`codec.go:145` in v8.5.6 is `return buffer[numDataBytes:]`. For `s[i:]` where `i > len(s)`, Go reports `slice bounds out of range [i:len(s)]`, i.e. `[8:4]`. So `numDataBytes` exceeded the bytes left in the cop response by exactly the right amount.

Edge → H₁: the cop response and the decoder disagree about column types/widths.

## H₁ — Decoder's column types disagree with cop-side encoded types

- **Perturbation.** Compare cascades vs volcano EXPLAIN — both pick the same plan structurally: `IndexReader → cop[Limit → Selection(not isnull c6) → IndexFullScan cover_idx_3120(c3,c4,c6) keep order:true]`.
- **Observation.** Plan shape is identical. Only the construction path through cascades differs. The same `physicalop.FindBestTask` machinery runs underneath, but the cascades wrapper produces a slightly different `IndexReader` (likely in schema / column-type list).
- **Numerical fingerprint.** The panic prints `[high:low]` from `goPanicSliceB`:
  - With 1 row: `[8:4]` — `numDataBytes` overshoots remaining buffer by `8 - 4 = 4` bytes.
  - With 50 rows: `[256:128]` — overshoots by `256 - 128 = 128` bytes.
  - Ratio is exactly 2:1 across both.
- **Interpretation.** The index `cover_idx_3120` has columns **`(c3 INT, c4 FLOAT, c6 INT)`** = (8 bytes, 4 bytes, 8 bytes). If the decoder's column-type list is mis-aligned by one position so that it reads the c4 column slot as if it were a (subsequent) INT, it consumes 4 bytes of c4's encoding but reserves 8 bytes for the slot. The chunk batch size on the first read is 32 rows (TiDB initial chunk size). So:
  - Column slot N: decoder expects INT (8 bytes × 32 = 256). Cop sent FLOAT (4 bytes × 32 = 128). Decoder skips 256 bytes forward; buffer only had 128 left → `[256:128]`.
  - With 1 row in the result: 8 vs 4 → `[8:4]`.
- **Status.** Confirmed by the numbers. The diagnosis is "cascades-built `IndexReader` schema has a type-list that disagrees with the cop-side column ordering."
- **Trajectory shape.** Divergent — the 2:1 ratio is too clean to be coincidence; it pins down the column geometry.

## H₂ — Where does the mismatch originate?

Cascades enters via `CascadesOptimize` (pkg/planner/core/optimizer.go:298) → `normalizeOptimize` + `cas.Execute` + `impl.ImplementMemoAndCost`. The implementation rules (`impl/impl_and_cost.go`) just dispatch into the same `physicalop.FindBestTask`. But:

- `normalizeRuleList` and `logicalRuleList` are the same slice (`optRuleList`) today, so the logical plan should be identical.
- The split happens after physical implementation, in how the `PhysicalIndexReader` gets its `Schema()` / column-type list resolved before being handed to the executor builder.
- Likely site: `ResolveIndices` on the cascades path (called at `impl_and_cost.go:94`) or a post-cascades projection-elimination step that re-orders/prunes columns in the IndexReader but doesn't propagate to the cop column list embedded in `PhysicalIndexReader.tablePlans` / `dagReq`.

**Frontier edges** (left for maintainers):

- E₁. Capture the `PhysicalIndexReader` from both planners at the moment it's handed to the executor builder; compare `IndexReader.Schema().Columns`, `IndexReader.OutputColumns`, and the `dagReq.OutputOffsets` / pushed `Columns` list.
- E₂. Check whether `task_opt_group_expression.go` or one of the cascades rules in `rule/ppd` / `rule/apply` prunes c4 from the IndexReader's logical schema in a way that volcano's `BaseLogicalPlan.FindBestTask` doesn't.
- E₃. Inspect `IndexReaderExecutor` build in `executor/builder.go` for cascades-vs-volcano divergence in column-type derivation.

The expression indexes (e.g. `expr_idx_323 ON ((c6 + 0))`) probably aren't directly involved — they sit on virtual columns that aren't in the chosen index — but the many `ANALYZE TABLE` + `CREATE INDEX` cycles may be required to nudge the cost model into picking `cover_idx_3120` rather than `range_idx_3120 (c3)`. The cheaper single-column index would only return `c3` and wouldn't trigger the geometry mismatch.

## Reframe — this is a one-off "reported-back" investigation

- The bug is in cascades schema/column-list bookkeeping after physical plan finalization. Patching it correctly requires deciding where the canonical IndexReader column list lives in the cascades path; that's a maintainer decision, not a drive-by patch.
- Cascades is experimental (`tidb_enable_cascades_planner=0` by default in production).
- Our contribution: precise stack trace, the 2:1 fingerprint, and the column-geometry interpretation. Posting back as a maintainer comment, not a PR.

## Provenance / status

- Reproduced on `pingcap/tidb:v8.5.6` (unistore) with the issue's exact SQL. Panic appears verbatim. Stack trace captured from `docker logs`.
- Same query under volcano returns the correct row.
- Both planners pick the same plan shape per `EXPLAIN`; the divergence is in column-type bookkeeping inside the IndexReader the executor receives.
- Halt — produce maintainer-facing comment, not a PR. Confidence in the diagnosis: ~85% (induction-grade evidence from the numerical fingerprint and the volcano A/B; abduction on which cascades code site is the culprit).

## Reasoning mode table

| Claim | Mode | Confidence |
|---|---|---|
| Cascades planner is required to repro | Induction (A/B run) | 99% |
| Panic site is `codec.go:145` (`return buffer[numDataBytes:]`) | Deduction (stack trace) | 99% |
| 2:1 byte ratio = decoder INT(8) vs cop FLOAT(4) per value | Deduction (arithmetic on goPanicSliceB args) | 95% |
| Mismatch is in cascades-built IndexReader column list | Abduction (only cascades repros; plan shape matches volcano) | 75% |
| Specific site within cascades (ResolveIndices / column-list propagation) | Abduction (unverified) | 50% |

## Pruning log

- *Killed*: "panic is inside cascades planner code." Stack trace shows it's in the chunk decoder under IndexReaderExecutor, downstream of optimization.
- *Killed*: "expression indexes cause the panic directly." cover_idx_3120 is a normal index over real columns; the expression indexes likely matter only as cost-model nudges.
- *Killed*: "slice op `s[:hi:max]` at codec.go:141 is the panic site." Three-index slices with `hi==max` don't trigger goPanicSliceB-style `[i:j]` panics with `i>j`; the single-index slice at 145 does, and matches the geometry.
