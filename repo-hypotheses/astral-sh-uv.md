# Triage Graph: astral-sh/uv (kimjune01)

**Scan date:** 2026-05-09

## Scan Table

| # | Title | State | Score | Effort | Signal | Status |
|---|-------|-------|-------|--------|--------|--------|
| 19326 | `uv sync --dev --locked --quiet` missing error message | OPEN | 7/10 | Small (~4 lines Rust + tests) | bug label, confirmed | COMMITTED |

## I19326: --quiet swallows lock mismatch error

### Root Cause

`uv lock --check --quiet` and `uv sync --locked --quiet` use `printer.stderr()` for the lock-mismatch diagnostic. `--quiet` suppresses `stderr()` output, so the user gets exit code 1 with no explanation.

### Fix (~4 lines + 2 tests)

Replace `printer.stderr()` with `printer.stderr_important()` in three call sites:
- `crates/uv/src/commands/project/lock.rs`
- `crates/uv/src/commands/project/sync.rs` (2 sites)
- `crates/uv/src/commands/workspace/metadata.rs`

Two new integration tests (`check_outdated_lock_quiet` and `locked_quiet`) confirm the error message prints under `--quiet`.

### Competing PRs

None found for #19326.

### PR Viability: HIGH

**For:** Clean bug fix. Confirmed by maintainers (bug label). Small, focused change. `stderr_important()` is the established pattern — no design decision needed.
**Against:** Org-blocked. 2 ruff PRs already open on astral-sh org (#25066, #25073). Must wait for those to clear.

### Risk

Low technical risk. Primary risk is org-level throughput — astral-sh may deprioritize external PRs while internal roadmap items land.

### Org Block

astral-sh has 2 open PRs from kimjune01 on ruff. Drip queue holds this until those resolve.

---

*Committed on branch `fix/quiet-lock-mismatch-error`. Not pushed — org-blocked.*
