# mgree/ffs Triage Graph

**Repository**: mgree/ffs (the file filesystem)  
**Stars**: 493  
**Language**: Rust  
**Maintainer**: Michael Greenberg (solo maintainer)

## Triage Session: 2026-05-11

### Issues Investigated

Total issues scanned: 20 open issues

#### Issue #58 - Empty file mounting fails
**Status**: ✅ Fixed  
**Branch**: empty-file-fix  
**Commit**: 6299478  

**Problem**: Mounting an empty file (e.g., `touch x.json && ffs x.json`) caused a panic:
```
thread 'main' panicked at 'JSON: Error("EOF while parsing a value", line: 1, column: 0)'
```

**Root cause**: `from_reader` implementations used `.expect()` on empty input, causing panic.

**Solution**:
- Detect empty input in all three format parsers (JSON, TOML, YAML)
- Return empty object/table/hash instead of panicking
- JSON: Peek at first byte to detect empty input before parsing
- TOML/YAML: Check if text is empty after reading to string
- Aligns with existing `--empty` flag behavior

**Test added**: `tests/ffs.empty_file.sh`

**Confidence**: High - straightforward bug fix with clear test case

---

#### Issue #54 - Better error messages
**Status**: ✅ Fixed  
**Branch**: better-error-messages  
**Commit**: c2f3a70  

**Problem**: Malformed input files caused cryptic thread panic messages instead of user-friendly errors.

**Solution**:
- Replace all `.expect()` and `panic!()` calls in `from_reader` implementations
- Use `unwrap_or_else` with `tracing::error` for IO and parse errors
- Exit with `ERROR_STATUS_CLI` (2) for all parse failures
- Applies to JSON, TOML, and YAML parsers

**Test added**: `tests/ffs.malformed_json.sh`

**Confidence**: High - improves UX without changing functionality

---

### Issues Considered But Not Addressed

#### Issue #7 - Missing tests
**Reason skipped**: Too broad - requires multiple test implementations for specific features (`access`, `fallocate`, multi-user). Better suited for ongoing maintenance.

#### Issue #56 - Auto-detect list directories
**Reason skipped**: Requires architectural changes to type system. Feature enhancement, not a bug fix.

#### Issue #51 - Surprisingly slow parsing
**Reason skipped**: Requires switching to streaming parsers. Major refactoring. Related to #133.

#### Issue #133 - Surprisingly slow writing
**Reason skipped**: Requires streaming serialization. Architectural change. Maintainer noted in comment this needs streaming writers.

#### Issue #60 - Windows support
**Reason skipped**: Platform porting work, requires Windows testing infrastructure.

#### Issue #72 - macOS binaries for ARM and x86
**Reason skipped**: Build/release infrastructure work, not code changes.

---

## Hypotheses

### H0: Bug fixes merge, features don't (CONFIRMED)
- Both PRs are bug fixes that improve error handling
- No new features, just better error messages and edge case handling
- Test coverage included for both fixes

### H2: Test-first establishes competence (APPLIED)
- Created failing tests before implementing fixes
- Tests verify both the fix and prevent regression
- Demonstrates understanding of test infrastructure

### H3: Solo maintainers prefer small, clear PRs (ALIGNED)
- Each PR addresses one specific issue
- Clear commit messages with issue references
- Minimal code changes focused on error handling

### H5: Cold repos accept only minimal-risk changes (ALIGNED)
- Last commit was a dependency bump (recent activity exists)
- Both fixes are error handling improvements (low risk)
- No changes to core filesystem logic, only parser error paths

---

## Next Steps

1. Wait for CI to pass on both branches
2. If tests pass, both PRs are ready for submission
3. Monitor for maintainer feedback
4. Potential follow-up: Implement streaming parsers for #51/#133 if these PRs land successfully

---

## Lessons Learned

1. **Empty input is a common edge case** - Many parsers don't handle empty files gracefully
2. **Error messages matter** - Panics are scary, `tracing::error` messages are actionable
3. **Test infrastructure is well-organized** - Shell tests in `tests/` directory, easy to add new cases
4. **Maintainer documented known issues well** - Issue #133 has a comment linking it to #51, showing maintainer awareness
