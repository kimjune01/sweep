# Triage Graph: clap-rs/clap

## Scan (2026-05-09)

User: kimjune01. 14K+ stars, Rust CLI argument parser.
Status: First contribution. UX improvement for a 3-year-old issue.

### Triaged issues

| # | Score | Signal | Title | Fix branch | Gate | Status |
|---|-------|--------|-------|------------|------|--------|
| 3604 | 4 | Enhancement, long-standing (2022), clear acceptance criteria | Suggest removing `--` when a known flag follows it | `fix/3604-suggest-remove-double-dash` | test: PASS | READY |

### Fix details

**#3604** (3 files, +84)
- File: `clap_builder/src/error/mod.rs` (+35)
  - New `unnecessary_double_dash_flag` error constructor with styled suggestion message
- File: `clap_builder/src/parser/parser.rs` (+23)
  - After `--` separator, checks if arg looks like a flag and matches a known option/flag in the command's keymap
  - Handles both long (`--dev`) and short (`-d`) flags
- File: `tests/builder/error.rs` (+26)
  - Test: `flag_used_after_double_dash` verifies the new error message
- Before: `app -- --dev` shows generic "unexpected argument '--dev'" with no actionable suggestion
- After: shows "flag '--dev' exists; to use it, remove the '--' before it"

### Competing PRs

None found for #3604.
