# pingcap/tiflash#10845 — text→JSON cast: JSON_EXTRACT result inconsistency

**Status: HALT at policy gate (maintainer-self-PR pattern).**

## Issue

`JSON_EXTRACT(text_col, '$.k')` on a `TEXT` column under TiFlash returns inverted `IS NULL` / `IS NOT NULL` results: rows with valid JSON values are matched by `IS NULL` (and excluded by `IS NOT NULL`). Same query on a `JSON` column returns correct results.

Plan diff (from JaySon-Huang's comment):
- TEXT path inserts an extra `cast(... as json BINARY)` before `json_extract`.
- JSON path runs `json_extract` directly.
- Both then `cast(... as var_string)` and `isnull(...)`.

## Halt reason

- Reporter `yongman` opened the issue 2026-05-15 03:36Z.
- Same author opened PR #10846 "functions: save FieldType as value instead of ptr in json function" against the same root cause within hours.
- Contributor `JaySon-Huang` already published the root cause in the issue comments:
  > `StorageDisaggregatedColumnar` (added in #10842) creates a temporary `FilterConditions` and builds `FunctionCastStringAsJson`. `FunctionCastStringAsJson` keeps only a ptr to the `tipb::FieldType`, which becomes invalid after the temporary goes out of scope.
- Reference: `dbms/src/Storages/StorageDisaggregatedColumnar.cpp#L326-L352` on `yongman/tiflash@013f968`.

Matches [[maintainer-self-pr-halt]]: reporter == WIP-PR author, root cause already published, no opening for an outside contributor.

## Diagnosis (recorded, not shipped)

**H₀ (confirmed by comment, deduction, ~95%):** the `tipb::FieldType*` held by `FunctionCastStringAsJson` dangles after the temporary `FilterConditions` instance in `StorageDisaggregatedColumnar` is destroyed. The cast then reads garbage field-type metadata, which flips the nullability/return-type behavior of the cast→`json_extract`→cast-to-`var_string`→`isnull` chain. JSON-typed columns bypass the cast entirely and are unaffected.

**Fix shape (per PR #10846 title):** store `FieldType` by value instead of pointer in the JSON function. Reasonable and minimal.

## Frontier

Closed by policy gate. No perturbations run, no PR drafted, no comment posted.

## Provenance

- Issue: https://github.com/pingcap/tiflash/issues/10845
- Author PR: https://github.com/pingcap/tiflash/pull/10846 (open, same author)
- Regression introduced by: PR #10842 (`StorageDisaggregatedColumnar`)
- Root-cause comment: JaySon-Huang, 2026-05-15 05:35Z
