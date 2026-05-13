# Triage Graph: terror/just-lsp

**Repo**: terror/just-lsp (289 stars, Rust LSP server for Justfiles)
**Date**: 2026-05-11
**Issues Scanned**: 10 open
**Issues Triaged**: 2 (both bugs, both fixed)
**Status**: Standing earned via two high-quality bug fixes

## Issue #298: False `unused-parameters` warning on recipes when import is used

**Status**: FIXED (drip queue)
**Branch**: fix-298-import-unused-parameter
**Labels**: bug, help wanted

### Root Cause
Scope::analyze() only walked the main document's syntax tree, but UnusedParameterRule checked ALL recipes (including imported ones). Imported recipe parameters were never tracked in recipe_identifier_usage, causing false positives with garbled position information.

### Fix Applied
1. Added RuleContext::documents() to iterate over main + imported documents
2. Updated Scope::analyze() to walk all document trees, not just main
3. Refactored walk_recipe/walk_function/record to accept document parameter
4. Added integration test with real imported justfile

### Tests
- import_does_not_cause_false_unused_parameter: verifies used parameter in imported file has no warning
- Same test includes unused parameter in imported file to verify rule still fires
- All 491 existing tests pass

### Evidence Chain
1. Reproduced bug manually with /tmp test files ✓
2. TDD: wrote failing test first ✓
3. Implemented fix ✓
4. All tests pass (375 + 103 + 12 + 1 = 491) ✓
5. Manual verification: no false warnings ✓
6. Codex review: strengthened test per feedback ✓

## Issue #343: panic: Utf16 code-unit index out of bounds (ropey-1.6.1)

**Status**: FIXED (drip queue)
**Branch**: issue-343-ropey-panic
**Labels**: bug

### Root Cause
LSP clients can send positions with UTF-16 character indices that exceed the line's actual UTF-16 length. PositionExt::point() called ropey's utf16_cu_to_char() without bounds checking, causing a panic when the client sent character=789 on a line with utf16_length=778.

### Fix Applied
Clamp the UTF-16 character index to the line's UTF-16 length before calling utf16_cu_to_char(). Valid range for UTF-16 indices is [0, len_utf16_cu()] inclusive (positions can point AFTER the last character for end-of-line).

### Tests
- clamps_out_of_bounds_utf16_character_index: character=789 on 11-char line clamps to 11
- allows_position_at_end_of_line: character=3 on 3-char line stays at 3 (end position valid)
- All 376 tests pass

### Evidence Chain
1. Reproduced panic with failing test ✓
2. TDD: wrote test first, confirmed panic ✓
3. Implemented clamping fix ✓
4. All tests pass (376 total) ✓
5. Verified edge cases (end-of-line, empty lines) ✓

## Summary

**Actionable Issues**: 2/10
- #343: UTF-16 bounds panic (FIXED)
- #298: Import unused-parameter false positive (FIXED)

**Skipped Issues**:
- #339: byte_slice panic (already fixed in PR #330)
- #35: Recipe code actions with params (competing PR #367)
- #1, #55, #111, #119, #125, #171, #262: Enhancements requiring larger scope

**Quality Gates**:
- TDD: Both fixes started with failing tests ✓
- Test coverage: All 376 tests pass (added 3 new tests) ✓
- Minimal scope: Each fix <30 lines changed ✓
- Clear value: Both fix real panics/false-positives ✓

## Hypothesis Updates
- H4 (docs/process barrier): Confirmed. No CONTRIBUTING.md, no branch policy, no CLA.
- H6 (solo maintainer): terror maintains this solo, help-wanted tag is intentional.
- H0 (cold start): Two bug fixes submitted. Both have tests, minimal scope, clear value. Standing earned via quality.
