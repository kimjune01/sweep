# vavallee/bindery#549 — hypothesis graph

**Issue**: `internal/db/history.go` uses `SELECT *` against `history`, with a positional `rows.Scan(...)` mapping. Future column add/drop/reorder silently corrupts reads.

## H₀ — observation

- **Claim**: every `SELECT` in `internal/db/history.go` is `SELECT *`, and every read goes through one `query` helper that positional-Scans six fields in a fixed order.
- **Perturbation**: read the file, grep for `SELECT *` across `internal/db/`.
- **Trajectory**: divergent confirmation.
  - Four call sites (lines 39, 43, 47, 51) all use `SELECT *`.
  - `query` (lines 66-84) scans into `&e.ID, &e.BookID, &e.EventType, &e.SourceTitle, &e.Data, &e.CreatedAt`.
  - Schema (`internal/db/migrations/001_initial.sql:166-173`) defines `history` columns in matching order today: `id, book_id, event_type, source_title, data, created_at`.
  - No other `SELECT *` in `internal/db/` — issue's "apply same pattern elsewhere" is vacuous, `history.go` is the only site.
- **Provenance**: 001_initial.sql is the original schema; no subsequent migration touches `history`. The coupling is latent — works today, breaks on the first reorder/add.
- **Status**: confirmed. Mode: deduction (read code).

## H₁ — issue's suggested column list is wrong

- **Claim**: the issue body proposes columns `id, book_id, event_type, source, message, created_at`. The actual schema has `source_title, data` (not `source, message`). Naively pasting the suggestion would compile but Scan would error at runtime: `no such column: source`.
- **Perturbation**: cross-check issue text vs. migration vs. Scan targets.
- **Trajectory**: divergent. The issue author misremembered column names. Fix must use the real names.
- **Status**: confirmed. Mode: deduction.

## H₂ — fix shape

- **Claim**: a single package-level `const historyColumns = "id, book_id, event_type, source_title, data, created_at"` consumed by all four queries makes the Scan order explicit and the column set reviewable. No behavior change today.
- **Regression test**: add a column to the in-memory `history` table after schema init, then call `List`. With `SELECT *`, Scan fails (`expected 6 destination arguments in Scan, not 7`). With the explicit list, Scan still maps the original six. The test fails on master, passes on the fix.
- **Compat**: zero behavior change for the current schema — same six columns, same order. Test added (in `internal/db/history_test.go`).
- **Status**: proposed; verified by `go test ./internal/db/ -run History`.

## Frontier

Closed. Single-file change, mechanical, with a regression test that proves the coupling is broken.

## Reasoning mode table

| Node | Mode | Confidence |
|------|------|-----------|
| H₀ | deduction | 99% |
| H₁ | deduction | 99% |
| H₂ | deduction + induction (test) | 95% |
