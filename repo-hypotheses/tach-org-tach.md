# Triage Graph: tach-org/tach

**Hypothesis**: H2/H5 — Python/Rust architecture linter, clean issues, low competition  
**Date**: 2026-05-09  
**Result**: SUCCESS — 1 PR queued

## Repository Overview

- **Type**: Python/Rust hybrid (maturin project)
- **Purpose**: Architecture linter for Python modular monoliths
- **Activity**: Active maintenance (DetachHead is primary maintainer)
- **Open Issues**: 30
- **Open PRs**: 6
- **Competition**: Low (no competing PRs on investigated issues)

## Issue Analysis

### High-Priority Bugs (Fixed)

**#845: Syntax errors reported as warnings, don't affect exit code**
- **Type**: Bug (exit code behavior)
- **Root cause**: `DiagnosticError::ImportParse` creating `Diagnostic::new_global_warning` instead of `new_global_error`
- **Fix**: Changed to `new_global_error` in check_internal.rs:227
- **Branch**: `fix/validate-module-dependencies`
- **Competing PRs**: None

**#846: Syntax errors reported as "unknown error" in tach check**
- **Type**: Bug (error message accuracy)
- **Root cause**: `PythonParse` errors falling through to catch-all `Err(_)` case
- **Fix**: Added `| Err(DiagnosticError::PythonParse(_))` to syntax error handler
- **Branch**: `fix/validate-module-dependencies` (same as #845)
- **Competing PRs**: None

### Investigated (Not Actioned)

**#889: .tach cache dir should contain .gitignore**
- **Status**: Already fixed in codebase (python/tach/cache/setup.py:24-31)
- **Evidence**: Test exists (test_cache.py:22), gitignore created with content `*`
- **Action**: Issue can be closed (not our place to close, maintainer will)

**#876: No error when depends_on refers to non-existent module**
- **Type**: Validation enhancement
- **Complexity**: Requires config validation layer
- **Decision**: Deferred (more complex than time allows, not a critical bug)

**#875: Module not found reported as warning, should be error**
- **Type**: Similar to #845
- **Status**: Skipped (focus on syntax error issues first)

## Technical Notes

### Codebase Structure
- Rust core: `src/` (diagnostics, checks, config, commands)
- Python wrapper: `python/tach/` (CLI, utilities, cache)
- Build: maturin (Rust extension for Python)
- Tests: pytest + cargo test

### Error Handling Pattern
```rust
match pipeline.diagnostics(project_file) {
    Ok(diagnostics) => diagnostics,
    Err(DiagnosticError::Io(_)) => Warning(SkippedFileIoError),
    Err(DiagnosticError::ImportParse(_)) => Error(SkippedFileSyntaxError), // Fixed
    Err(DiagnosticError::PythonParse(_)) => Error(SkippedFileSyntaxError), // Fixed
    Err(_) => Warning(SkippedUnknownError),
}
```

## Competition Analysis

No competing PRs found for #845 or #846. Search queries:
- "syntax" — 0 relevant PRs
- "error" — 0 relevant PRs  
- "warning" — 0 relevant PRs

## Outcome

**Branch**: `fix/validate-module-dependencies`  
**Commits**: 1 (9fcba29)  
**Issues Fixed**: #845, #846  
**Lines Changed**: 2 insertions, 2 deletions (1 file)  
**Confidence**: High (simple, well-defined bug fix)

## Next Steps for /drip

1. Push branch to fork
2. Create PR with:
   - Title: "fix: report syntax errors as errors, not warnings"
   - Body: Links to #845 and #846, explains behavior change
   - Test plan: Create file with syntax error, run `tach check`, verify exit code != 0
