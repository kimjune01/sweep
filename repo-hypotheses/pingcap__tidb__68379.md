# pingcap/tidb#68379 — nil pointer in AllocBatchAutoIncrementValue

**Issue:** First-time reporter, v8.5.1. Intermittent `runtime error: invalid memory address or nil pointer dereference` on `INSERT` into a table that has **AUTO_RANDOM clustered PK + AUTO_INCREMENT on a non-PK unique key**. "After restarting TiDB, the INSERT works normally, but after running for a while, this error occurs again."

Stack (v8.5.1):
```
table.AllocBatchAutoIncrementValue (pkg/table/table.go:517)
↑ (*InsertValues).lazyAdjustAutoIncrementDatum (pkg/executor/insert_common.go:878)
```

Line 517 in v8.5.1 = `alloc.Alloc(ctx, uint64(N), ...)`. The deref target is `alloc`, returned from `Allocators.Get(AutoIncrementType)`, which returns `nil` when no matching allocator exists.

## Reasoning mode table

| Claim | Mode | Confidence |
|---|---|---|
| `alloc` is nil at panic site | Deduction (read code, only one nil-able value) | 99% |
| `alloc` came from `Allocators.Get(AutoIncrementType)` returning nil | Deduction | 99% |
| Get returns nil iff no matching `AllocatorType` is in `Allocs` slice | Deduction | 99% |
| For this DDL, allocator set *should* be `[RowIDAllocType, AutoRandomType]` with `SepAutoInc=false` | Deduction (traced `NewAllocatorsFromTblInfo` against this `tblInfo`) | 90% |
| `Get(AutoIncrementType)` with `SepAutoInc=false` remaps to `RowIDAllocType` and finds it | Deduction | 95% |
| Therefore allocator should be present; nil indicates a corner-case construction or rebuild path missed it | Abduction | 75% |
| Defensive nil-check at the call site converts a panic into a diagnosable error | Deduction | 99% |
| Defensive nil-check addresses **root cause** | — | NO. It only converts the symptom. |

## H₀ — Direct allocator inspection (Deduction)

`v8.5.1:pkg/table/table.go:514-522`:

```go
alloc := t.Allocators(sctx.GetTableCtx()).Get(autoid.AutoIncrementType)
minv, maxv, err := alloc.Alloc(ctx, uint64(N), int64(increment1), int64(offset))  // line 517
```

`pkg/meta/autoid/autoid.go:238-251` — `Get` returns `nil` when no matching allocator exists. Caller does not check. **Trajectory: divergent** — the cause of the panic is fully characterized at the call site.

**Kill condition:** any other nilable value at line 517. None — `t`, `sctx`, `ctx` would have crashed earlier; `increment1`, `offset` are ints; `Allocators` returns a struct value, not a pointer.

**Edge:** Why is the AutoIncrement allocator missing for a table that has `id BIGINT AUTO_INCREMENT`?

## H₁ — Allocator set built without an AutoIncrement/RowID entry at construction

`pkg/meta/autoid/autoid.go:683-708` (`NewAllocatorsFromTblInfo`):

For this table (`PKIsHandle=true` via clustered AUTO_RANDOM, `hasAutoIncID=true`, `AutoIDCache=0` → `SepAutoInc()=false`):

- `hasRowID = !PKIsHandle && !IsCommonHandle = false`
- branch `hasRowID || (hasAutoIncID && !SepAutoInc)` → **true** → RowIDAllocType allocator added ✓
- branch `hasAutoIncID && SepAutoInc` → false → no AutoIncrementType allocator
- branch `hasAutoRandID` → true → AutoRandomType allocator added

So `Allocs = [RowID, AutoRandom]`, `SepAutoInc=false`. `Get(AutoIncrementType)` remaps to RowIDAllocType and finds it.

**Trajectory: convergent for the expected case.** This case shouldn't crash.

**Edges (open frontier):**

- **H₁ₐ.** `AutoIDCache` flips to `1` (→ `SepAutoInc=true`) after creation, but the cached `t.allocs` was built with `SepAutoInc=false` and contains a `RowID` allocator. When `Get(AutoIncrementType)` is called with the new `tblInfo`, `Allocators.SepAutoInc` (captured at construction) is *still* false, so the remap to RowID happens correctly — UNLESS the rebuild path replaces `t.meta` but keeps `t.allocs`. Status: **untested**. Required perturbation: trigger `ActionModifyTableAutoIDCache` on a live table with this schema and re-insert.
- **H₁ᵦ.** Table info `Version` upgrade crosses `TableInfoVersion5` boundary at runtime, flipping `SepAutoInc()`. Same shape as H₁ₐ. Status: **untested**.
- **H₁ᵧ.** Autoid service (`tidb_enable_autoid_service`) path produces an `Allocators` view that omits the relevant type after a service restart / leadership change, and the panic correlates with the autoid service connection state. "After restarting TiDB it works, then fails after a while" fits this signature. Status: **untested** — no autoid-service-side code read yet.
- **H₁ᵨ.** Schema reload after a DDL on this table (e.g., `ALTER ... AUTO_INCREMENT = ...`, `ALTER ... AUTO_RANDOM_BASE = ...`, RECOVER, FLASHBACK) constructs a new `TableCommon` with a partial allocator set. The single assignment site `t.allocs = allocs` (`pkg/table/tables/tables.go:246`) is only called from constructors, so this requires a constructor path that builds an unexpected set. Status: **untested**.

## H₂ — Race / mid-rebase observation

The autoid allocator has been the subject of historical data races (`#40584`, closed 2023). Possibility that during a `RebaseAutoID` or similar concurrent operation, a goroutine observes a transiently-empty `Allocs` slice. Code read shows `t.allocs` is only written once at construction, but the underlying slice in `Allocators` could be aliased and mutated.

**Status:** untested, low-confidence (no `Allocs` mutation site found by grep).

## H₃ — `GetAutoIncrementColInfo` returns nil under some flag-clearing path

`pkg/meta/model/table.go:328-336`: scans columns for `mysql.HasAutoIncrementFlag`. If a DDL path (column drop, column type change, swap-with-another-PK) transiently clears the flag, `hasAutoIncID=false`, and at construction time **no** AutoIncrement-family allocator is added (because `hasRowID=false` and `hasAutoIncID=false`). Then a subsequent insert from a session with stale (or post-DDL) `tblInfo` panics.

**Status:** untested. **Edge:** trace which DDLs on a clustered-AUTO_RANDOM table can rebuild `TableCommon` with the autoinc flag cleared.

## Provenance

- v8.5.1 tag, `pkg/table/table.go:517` — `alloc.Alloc(...)` is the panic site. The line has been structurally identical on master (`pkg/table/table.go:499`).
- One assignment site to `t.allocs` (`pkg/table/tables/tables.go:246`); the field is never reassigned. Rules out post-construction nullification.
- No existing PRs or issues match the signature (`gh search issues "AllocBatchAutoIncrementValue"` → only this issue + a 2023 closed data-race issue).
- Reporter is a first-time contributor; no follow-up comments, no maintainer triage yet.

## Surface fix vs. root cause

A **surface fix** is straightforward: nil-check `alloc` and return a descriptive error.

```go
alloc := t.Allocators(sctx.GetTableCtx()).Get(autoid.AutoIncrementType)
if alloc == nil {
    return 0, 0, errors.Errorf("no auto_increment allocator for table %d (%s)", t.Meta().ID, t.Meta().Name.O)
}
```

This converts the panic into a diagnostic error message that exposes the underlying state for any future report. It does **not** fix the root cause — it makes the next report actionable.

A **root-cause fix** requires reproducing the "after running a while" condition. Without a reliable repro, any structural patch is speculative. The intermittency + restart-clears-it signature is most consistent with an autoid-service or schema-reload corner case (H₁ᵧ, H₁ᵨ), but none of those hypotheses has been classified by a real perturbation in this investigation — the system was read, not poked.

## Graph state

| Node | Status | Trajectory |
|---|---|---|
| H₀: nil deref at table.go:517 = `alloc` nil | confirmed | divergent |
| H₁: allocator set construction analysis | partial (expected set is correct; corner cases open) | convergent for normal path |
| H₁ₐ: AutoIDCache flip rebuild | open | — |
| H₁ᵦ: TableInfoVersion upgrade rebuild | open | — |
| H₁ᵧ: autoid service state transition | open | — |
| H₁ᵨ: DDL-induced rebuild w/ partial allocs | open | — |
| H₂: race on `Allocs` slice | open, low prior | — |
| H₃: transient autoinc-flag clear during DDL | open | — |

## Halt — Phase 4

**Frontier is open.** All H₁/H₂/H₃ edges require either a live TiDB cluster to perturb, or a deeper read of the autoid-service and schema-reload paths that wasn't done here. The investigation produced a defensible diagnosis of the proximate cause and a clear menu of root-cause hypotheses, but no reproduction.

**No PR shipped.** Reasons:

1. **No reproduction.** "After running a while" is not a perturbation we can run from this side. Maintainers will (correctly) ask for one and any speculative patch is unprovable.
2. **Defensive nil-check is borderline-rejectable on tidb.** It hides rather than explains the bug, and the project's review culture historically prefers root-cause patches over defensive guards in hot paths. Worth offering only with an accompanying repro or a maintainer signal that the diagnostic-error form is wanted.
3. **No maintainer triage yet** on the issue (created 2026-05-14, only the welcome-bot has commented). Acting before the maintainer has weighed in risks duplicating their own diagnosis.

**Recommended next moves (operator decision):**

- Post a comment on the issue summarizing the diagnosis (alloc is nil → most likely H₁ᵧ or H₁ᵨ) and asking the reporter for: (a) whether autoid service is enabled (`tidb_enable_autoid_service`), (b) whether any DDL ran on this table during the "running a while" window, (c) the TiDB error log around the panic for any autoid-service reconnect or schema-load lines.
- If maintainer responds positively to a defensive nil-check as a stopgap, ship that as a one-line PR; otherwise, hold for repro.
