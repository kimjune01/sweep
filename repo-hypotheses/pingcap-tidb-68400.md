# pingcap/tidb#68400 — ALTER MODIFY COLUMN reports false truncation for multibyte chars

**Status:** Diagnosis converged. Single-line bug. Test + fix ready.
**Started:** 2026-05-16

## H₀ — Observation

> `varchar(3000) → varchar(2000)` rejects a value whose `CHAR_LENGTH` is 1007 (fits) but whose `LENGTH` is ~3021 bytes (Chinese, 3 bytes/char in UTF-8). MySQL VARCHAR semantics are character-based, so the rejection is wrong.

**Trajectory:** Divergent. The reported behavior contradicts MySQL semantics — VARCHAR(N) means N characters, not N bytes.
**Edge:** Where is the truncation gate that's measuring in bytes?

## H₁ — bytes-vs-chars confusion in the modify-column precheck

**Hypothesis:** The precheck SQL that validates existing data against the shrunk type measures byte length, not character length.

**Perturbation:** Grep `pkg/ddl/modify_column.go` for the truncation error and inspect the condition.

**Result:** `pkg/ddl/modify_column.go:866`

```go
conditions = append(conditions, fmt.Sprintf("LENGTH(%s) > %d", checkColName, changingCol.FieldType.GetFlen()))
```

`LENGTH()` returns **bytes**. `FieldType.GetFlen()` for VARCHAR is **characters**. Direct unit mismatch.

**Trajectory:** Divergent confirm. Single line, exact mechanism match. Confidence: deduction, ~98%.

**Mode:** Abduction → Deduction (read the code, traced the units).

## H₁.provenance — git blame + adjacent work

- Introduced in commit `a84aea05` (2025-10-25, PR #63465: "ddl: make some `MODIFY COLUMN` skip row reorg").
- New optimization: skip the reorg backfill when a precheck SQL proves all existing rows fit the new type.
- Bug is in the precheck itself. The optimization is sound; the unit is wrong.
- Existing PR search (`gh pr list --search "modify column truncated multibyte"`): no PR addresses #68400.
- Issue filed 2026-05-15, no maintainer claim yet.

## H₂ — collateral damage: what else fires `LENGTH(col) > Flen`?

**Hypothesis:** Same `else` branch is hit for non-VARCHAR types where `Flen` is also not bytes (decimal display width, time width, enum/set), producing spurious truncation.

**Perturbation:** Read callers and the type-switch logic.

**Result:**
- `else` branch fires when at least one of `(oldTp, changingTp)` is non-integer, in a lossy change context.
- Most realistic hits: `varchar→varchar` shrink, `varchar→char`, `text→varchar`. All character types.
- Decimal/float/time changes flow into a different code path (the `IsIntegerType` branch was extracted specifically; numeric precision changes are handled by other checks earlier — `checkValueRange` is gated on whether the new type narrows the value space, and for floats/decimals the modify-column path validates via type-conversion semantics, not this SQL).
- The bug surfaces on character types; the unit-fix is scoped to character types.

**Mode:** Deduction. Confidence: ~90%. Open edge: confirm with gemini volley.

## Fix shape

In `buildCheckSQLFromModifyColumn`:

```go
} else {
    var lenFn string
    if types.IsBinaryStr(&changingCol.FieldType) {
        lenFn = "LENGTH"
    } else {
        lenFn = "CHAR_LENGTH"
    }
    conditions = append(conditions, fmt.Sprintf("%s(%s) > %d", lenFn, checkColName, changingCol.FieldType.GetFlen()))
    if oldTp == mysql.TypeVarchar && changingTp == mysql.TypeString {
        conditions = append(conditions, fmt.Sprintf("%s LIKE '%% '", checkColName))
    }
}
```

Rationale:
- `VARCHAR/CHAR/TEXT` (non-binary collation): Flen is **characters** → `CHAR_LENGTH`.
- `VARBINARY/BINARY/BLOB` (binary collation): Flen is **bytes** → `LENGTH` (current behavior).
- `types.IsBinaryStr` returns true when the column's collation is binary, which is the precise discriminator.

## Test

Reproduces the issue exactly: insert a multibyte value into `varchar(N)`, shrink to `varchar(M)` where `char_length(value) ≤ M < byte_length(value)`. Must fail on master, pass with fix.

## Graph state table

| Node | Status | Mode | Trajectory | Confidence |
|------|--------|------|------------|------------|
| H₀   | confirmed | observation | divergent | 99% |
| H₁   | confirmed | deduction | divergent | 98% |
| H₁.prov | confirmed | deduction | — | 98% |
| H₂   | partial | deduction | convergent | 90% |
| H₃   | open (deferred) | deduction | divergent | 95% |

## Verification

- Fix applied in `/tmp/tidb` (branch `fix-modify-column-multibyte`).
- New test `TestModifyColumnMultibyteCharLength` in `pkg/ddl/modify_column_test.go`:
  - Covers VARCHAR utf8mb4 shrink that fits by char count but not byte count → must succeed.
  - Covers VARCHAR utf8mb4 shrink that truly truncates → must error.
  - Covers VARBINARY shrink → byte semantics preserved.
- Result: test **fails on master** (proves bug), **passes with fix**.
- Adjacent regression suite `TestModifyColumnBetweenStringTypes` and `TestModifyColumnCharset` still pass.

## H₃ — latent bug: VARBINARY → VARCHAR precheck (out of scope)

**Hypothesis (from gemini volley):** Post-fix, `lenFn` is selected by `changingCol.FieldType`. For VARBINARY→VARCHAR, fix picks `CHAR_LENGTH`. TiDB's `builtinCharLengthBinarySig` (`pkg/expression/builtin_string.go:2587`) returns `int64(len(val))` — **bytes** — on binary input. So `CHAR_LENGTH(varbin_col) > char_flen` compares bytes against a character-count Flen.

**Perturbation:** Read `builtinCharLengthBinarySig.evalInt`; trace `isCharChange` (`IsTypeChar` returns true for both `TypeString` and `TypeVarchar`, so VARBINARY enters this path).

**Result:** Confirmed unit mismatch. But pre-fix used `LENGTH(varbin) > char_flen` — also a unit mismatch in the same direction. **Behavior unchanged by this PR.** This is a latent pre-existing bug, not a regression from #68400's fix.

**Proper fix (deferred):** `CHAR_LENGTH(CONVERT(col USING <new_charset>)) > flen` for non-binary new types, to decode bytes through the target charset before counting characters. Out of scope for this PR — the reported issue is VARCHAR→VARCHAR, the user-facing trigger.

**Mode:** Deduction. Confidence: ~95% that latent bug exists; not blocking this PR.
**Status:** Open frontier — separate ticket worth filing after the merge.

## Frontier

H₃: VARBINARY→VARCHAR latent unit mismatch. Pre-existing, not introduced by this fix. Defer.
