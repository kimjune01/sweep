# pingcap/tidb#68454 — hypothesis graph

## Issue
`CREATE INDEX` / `ALTER TABLE ADD INDEX` silently accepts `table_name.column_name` qualifiers (`b.c`, `xx.c`) on v8.5.2 and current master. MySQL 5.7 rejects. TiDB drops the qualifier and uses only the suffix, so `idx(a, b.c)` becomes `KEY (a, c)` with no error.

> Note: an earlier doc at this path claimed the bug was already fixed on master. That was wrong — git diff against HEAD (2ce45f0) shows `buildIndexColumns` had no qualifier check before this investigation, and `TestIndexColumnQualifiedName` did not exist.

## H₀ — Parser stores the qualifier; validator drops it
- **Mode**: deduction
- **Perturbation**: read `pkg/parser/parser.y:4632` (`IndexPartSpecification: ColumnName OptFieldLen OptOrder`) and `pkg/parser/ast/expressions.go:514` (`ColumnName{Schema, Table, Name CIStr}`).
- **Result**: parser populates `Column.Table` from `b.c`; the AST carries the qualifier.
- **Shape**: divergent confirm. Bug is downstream of the parser.

## H₁ — Bug locus is `buildIndexColumns` in `pkg/ddl/index.go:122`
- **Mode**: deduction
- **Perturbation**: read the loop body. Pre-fix:
  ```go
  for _, ip := range indexPartSpecifications {
      col = model.FindColumnInfo(columns, ip.Column.Name.L)
      if col == nil { return ..., ErrKeyColumnDoesNotExits... }
      ...
  }
  ```
- **Result**: `ip.Column.Schema` and `ip.Column.Table` are never consulted. The three call sites (`pkg/ddl/executor.go:4702, 4883, 5007` and `pkg/ddl/index.go:430`) cover ALTER TABLE ADD INDEX, CREATE INDEX, and inline CREATE TABLE keys — all paths in the repro.
- **Shape**: divergent confirm (bug locus).

## H₂ — Fix: reject any non-empty qualifier
- **Mode**: induction (fail-on-master / pass-on-fix)
- **Perturbation**: insert pre-check at top of the loop in `buildIndexColumns`. Reject any case where `Schema` or `Table` is non-empty (matches MySQL — MySQL's `key_part` grammar doesn't accept `tbl.col` at all, even when `tbl` matches the current table).
- **Validation**:
  - Added `TestIndexColumnQualifiedName` covering `b.c`, `xx.c`, `t.a`, `test.t.a`, inline `CREATE TABLE … KEY k(t2.a)`.
  - Stashed fix, ran test → **FAIL** on master (`An error is expected but got nil.` for `alter table t add index idx1(a, b.c)`).
  - Restored fix, re-ran → **PASS**.
  - Neighboring tests `TestSchemaNameAndTableNameInGeneratedExpr`, `TestParserIssue284` still pass.
- **Shape**: divergent confirm.

## Graph state
| Node | Status | Mode | Shape |
|------|--------|------|-------|
| H₀ parser stores qualifier | confirmed | deduction | divergent |
| H₁ bug locus = `buildIndexColumns` | confirmed | deduction | divergent |
| H₂ pre-check fix + test | confirmed | induction | divergent (fail→pass) |

## Frontier edges
- None open. FK `REFERENCES tbl(col)` lists go through a different validator and are out of scope.

## Pruning log
- Considered fixing in `parser.y` (reject qualified `ColumnName` in `IndexPartSpecification`). Killed: `ColumnName` is shared across many productions; validator-level fix covers all callers and is the minimal change.
- Considered allowing `t.c` when `t` matches the current table. Killed: MySQL rejects this case too; matching MySQL is the stated expectation.

## Files touched
- `pkg/ddl/index.go` — `buildIndexColumns` pre-check (`ErrWrongColumnName`)
- `pkg/ddl/db_integration_test.go` — `TestIndexColumnQualifiedName`
