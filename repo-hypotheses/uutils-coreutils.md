# Triage Graph: uutils/coreutils

## Scan (2026-05-09)

User: kimjune01. 18K+ stars, Rust coreutils reimplementation.
Status: Active sweep. Two fixes ready.

### Triaged issues

| # | Score | Signal | Title | Fix branch | Gate | Status |
|---|-------|--------|-------|------------|------|--------|
| 11656 | 5 | Bug, POSIX compliance gap, clear spec reference | date: handle POSIX O and E locale modifiers in strftime | `fix/date-oe-modifier-c-locale` | test: PASS | GATED (competing PR #11834) |
| 12157 | 7 | Bug, regression from PR #10235, breaks dd in restricted containers | dd: incorrectly depends on fcntl syscall | `fix-dd-fcntl-dependency` | test: PASS | READY |

### Fix details

**#11656** (2 files, +314 -32) - GATED
- Issue: date doesn't handle POSIX %O and %E locale modifiers
- Competing PR: #11834 already open
- Gate reason: Same issue being addressed
- File: `src/uu/date/src/format_modifiers.rs` (+289 -32)
  - Extended `ParsedSpec` to track optional `E`/`O` locale modifier
  - Updated parser grammar from `%[flags][width]:*[a-zA-Z]` to `%[flags][width][EO]?:*[a-zA-Z]`
  - Added `is_o_modifier_valid` and `is_e_modifier_valid` functions matching GNU date's acceptance/rejection behavior
  - Invalid modifier+specifier combos emit literal `%O<spec>` / `%E<spec>` like GNU
  - In C locale, valid modifiers are no-ops
- File: `tests/by-util/test_date.rs` (+57)
  - Tests covering valid and invalid modifier combinations for both `E` and `O`

**#12157** (1 file, +25 -13) - READY
- Issue: dd fails with "write error" when fcntl syscall is unavailable (e.g., in restricted containers)
- Root cause: `OwnedFileDescriptorOrHandle::from(io::stdout())` calls `try_clone_to_owned()` which uses fcntl internally
- Regression: Introduced in PR #10235
- Fix: Replace with borrowed File pattern using `ManuallyDrop::new(unsafe { File::from_raw_fd(fd) })`
- File: `src/uu/dd/src/dd.rs` (+25 -13)
  - `Output::new_stdout()`: Use ManuallyDrop pattern instead of OwnedFileDescriptorOrHandle
  - `Output::new_file_from_stdout()`: Use ManuallyDrop pattern, still calls fcntl for F_SETFL when needed on Linux/Android
  - Added `ManuallyDrop` and Windows raw handle imports
  - Removed unused `OwnedFileDescriptorOrHandle` import
- Test: `strace -o /dev/null -e inject=fcntl:error=ENOSYS dd if=/etc/pacman.conf` (requires Linux)
- All 85 unit tests pass

### Competing PRs

None found for #12157.
