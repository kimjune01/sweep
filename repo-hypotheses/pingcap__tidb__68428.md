# pingcap/tidb#68428 — Limit cannot find columns from non-covering index scan under cascades planner

**Issue:** https://github.com/pingcap/tidb/issues/68428
**Reporter:** @ZyanNo1 (community contribution label)
**State:** OPEN, no comments yet, filed 2026-05-16
**Repro:**

```sql
CREATE TABLE t(c0 INT PRIMARY KEY, c1 INT);
CREATE INDEX i ON t (c1);
SET SESSION tidb_enable_cascades_planner=1;
SELECT * FROM t ORDER BY c1 LIMIT 1;
-- ERROR 1105: Some columns of Limit_20 cannot find the reference from its child(ren)
```

Volcano (default) planner returns empty set. Cascades errors at `ResolveIndices`.

## H₀ — error site identified

**Hypothesis:** the error message comes from `resolveIndexForInlineProjection` complaining that a PhysicalLimit's PhysicalSchemaProducer schema is not contained (in order) by its child's schema.

**Perturbation:** grep for the error string.

**Result (deduction, 99%):** `pkg/planner/core/resolve_indices.go:184`, called from `resolveIndices4PhysicalLimit` at `pkg/planner/core/resolve_indices.go:236`. The `physical_index_join.go`/`merge_join.go`/`hash_join.go` sites use the same string but aren't reachable from this SQL (no join). Confirmed: Limit's schema must be an ordered subset of its child's schema, or this error fires.

**Trajectory:** divergent — confirms the error site precisely.
**Edge:** identify why the physical plan under cascades places a Limit over a child that doesn't expose c0 + c1.

## H₁ — cascades skips `preparePossibleProperties`

**Hypothesis:** cascades's physicalization portal (`ImplementMemoAndCost`) doesn't call `preparePossibleProperties(logic)`, while Volcano's `physicalOptimize` does. Without it, DataSource's available index orderings aren't seeded into the search, so the optimizer can't pick `IndexScan(i)` to satisfy the ORDER BY c1 property naturally, and ends up emitting a degenerate task whose Limit schema doesn't line up with the child's.

**Perturbation:** grep `preparePossibleProperties` across `pkg/planner`.

**Result (deduction, 95%):**
- Volcano calls it at `pkg/planner/core/optimizer.go:1053`, just before `physicalop.FindBestTask`.
- Cascades's `impl.ImplementMemoAndCost` (`pkg/planner/cascades/impl/impl_and_cost.go:66-99`) goes straight into `ImplementGroupAndCost` → `FindBestTask` with no possible-properties pass.
- The old (now-vestigial) cascades package in `pkg/planner/cascades/old/optimize.go:249` *did* call `preparePossibleProperties` — the new portal regressed it.

**Trajectory:** divergent — strong structural evidence that the cascades path is missing a step Volcano's `FindBestTask` machinery assumes has run.

**Edge:** confirm via actual plan dump that under cascades, the plan tree shape is Limit→IndexReader(IndexScan i, schema=[c1,handle]) rather than Limit→IndexLookUp[c0,c1].

## H₂ — degenerate IndexReader without IndexLookUp wrap

**Hypothesis:** the chosen physical plan is `Limit[c0,c1] → IndexReader[c1, _tidb_rowid] → IndexScan(i)`, missing the TableLookUp that would project c0 back in. Limit's schema includes c0 from `SELECT *`, but IndexReader's schema is the index columns only.

**Perturbation (designed, not yet run — requires built tidb-server):**
```sql
SET SESSION tidb_enable_cascades_planner=1;
EXPLAIN FORMAT='brief' SELECT * FROM t ORDER BY c1 LIMIT 1;
```
Expect the plan tree to show Limit over IndexReader rather than IndexLookUp. If `EXPLAIN` itself errors (likely, since it shares ResolveIndices), instead set `tidb_enable_telemetry=0` and inspect the partial plan via the planner trace.

**Status:** frontier — perturbation not run (no built binary on this workstation, only source). High confidence in prediction given H₁'s structural finding.

## H₃ — `normalizeOptimize` ≠ `logicalOptimize`?

**Hypothesis:** the logical rule lists differ between paths and that's responsible.

**Result (deduction, 99%):** killed. `pkg/planner/core/optimizer.go:78-80`:
```go
logicalRuleList   = optRuleList
normalizeRuleList = optRuleList
```
Identical rule lists. The difference is purely at the physicalization boundary.

**Trajectory:** divergent against. Edge closed.

## Graph state

| Node | Status | Mode | Confidence |
|------|--------|------|-----------|
| H₀ error origin = resolveIndexForInlineProjection / Limit | confirmed | deduction | 99% |
| H₁ cascades misses preparePossibleProperties | confirmed structural | deduction | 95% |
| H₂ Limit over IndexReader (no IndexLookUp) | frontier | abduction | 70% — needs plan dump |
| H₃ logical rule list divergence | killed | deduction | 99% |

## Frontier edges

1. **Run EXPLAIN under cascades to confirm H₂.** Requires building tidb-server. Predicted classification: divergent confirmation.
2. **Patch: add `preparePossibleProperties(logic)` between `normalizeOptimize` and `cascades.NewOptimizer`** (or inside `ImplementMemoAndCost` before `FindBestTask`). Predicted: if H₁/H₂ hold, this fixes the schema mismatch by letting IndexScan satisfy ORDER BY through the normal index-task builder path which constructs IndexLookUp for non-covering indexes.
3. **Independent angle:** are there other Volcano-pre-physical hooks the cascades path skips? `RecursiveDeriveStats` is called at `optimizer.go:1047` — check if the cascades portal handles stats derivation equivalently via `memo.copyIn`.

## Provenance notes

- `pkg/planner/cascades/cascades.go` and `impl/impl_and_cost.go` carry 2024/2025 copyright headers — the new cascades portal is recent. The `pkg/planner/cascades/old/` package still references `preparePossibleProperties`. The omission in the new portal looks like a porting miss rather than a deliberate redesign.
- Repo at `/tmp/tidb` is a shallow clone (depth 1) so git blame for the omission is unavailable here. Re-fetch with `git fetch --unshallow` to attribute.
- Issue is fresh (filed today), no maintainer comment yet, no linked PR.

## Pushout (blind-blind merge) — NOT RUN

Per the skill, a second model (codex) should have produced an independent diagnosis from the same evidence pack. **Codex usage limit hit** (rate-limited until 2026-05-17 23:54), so this pass is skipped. Hypothesis A above stands without an independent check; treat downstream confidence as ~10% lower than nominal until the pushout completes. Retry with `/gemini` or wait for codex reset.

## Halt / next actions

**Halt at Phase 4 (Report).** Phase 5 (prework) requires:
1. A built `tidb-server` to confirm H₂ via EXPLAIN, and to write a fail-on-master / pass-on-fix test.
2. The fix candidate is one-line shaped but ripples through the cascades portal contract — needs a TiDB committer's read on whether `preparePossibleProperties` belongs at the cascades entry, inside `ImplementMemoAndCost`, or whether stats/property prep should be folded into `memo.Init`.

**No PR.** The investigation produces a strong structural lead (H₁) and a falsifiable plan-shape prediction (H₂). The operator should either:
- Build TiDB locally and run H₂'s perturbation to confirm before shipping a one-line fix, or
- Post the diagnosis as a comment on the issue inviting a maintainer to confirm the plan shape, or
- Defer — cascades is experimental and the maintainer team may already know.

## Reasoning mode summary

- Deduction (read the code, traced consequences): H₀, H₁, H₃ — high confidence.
- Abduction (proposed from observation): H₂ — needs induction to confirm.
- Induction (ran the experiment): none yet — no built binary.
