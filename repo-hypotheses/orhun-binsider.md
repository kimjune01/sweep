# Triage Graph: orhun/binsider

Rust binary analyzer TUI. 4.2K stars. Active maintainer (orhun).

## Repository Context

- **Language**: Rust
- **Domain**: Binary analysis, ELF inspection, TUI
- **Activity**: High - regular releases and issue responses
- **Maintainer**: orhun (responsive, clear contribution guidelines)

## Issues Scanned

Total open issues: 24 (as of 2026-05-10)

### Selected for Implementation

**Issue #45**: Support searching for shared libraries
- **Labels**: enhancement, good first issue, effort: medium
- **Status**: IMPLEMENTED
- **Branch**: search-shared-libraries
- **Competing PRs**: None
- **Rationale**: Clear mechanical acceptance criteria, matches existing search pattern in other tabs
- **Implementation**: Added case-insensitive filter to General tab with "/" search key
- **Review**: Passed codex + gemini. Gemini caught performance issue (redundant .to_lowercase() calls), fixed.
- **Hypothesis Support**: H1 (good-first-issue label), H2 (mechanical acceptance criteria)

### Other Good First Issues Reviewed

**Issue #22**: Sort Symbols by Name or Address
- **Status**: SKIPPED - Has competing PR #99 (open since Oct 2024, no review)
- **Note**: Stale PR suggests maintainer may not be prioritizing this feature

**Issue #92**: Visible cursor doesn't move with index in search
- **Status**: SKIPPED - Has competing PR #93 (WIP, filed by issue reporter)
- **Note**: Author is already working on it

**Issue #35**: Support displaying general file information on Windows
- **Status**: SKIPPED - Requires Windows testing environment
- **Note**: Cross-platform issue, harder to verify without Windows

**Issue #17**: Print linked libraries as tree
- **Status**: NOT SELECTED - More complex than #45, requires understanding libtree
- **Complexity**: Medium-high, tree visualization

**Issue #7**: Support tweaking dynamic analysis options
- **Status**: NOT SELECTED - Requires design decisions on CLI vs TUI interface
- **Complexity**: Medium, API surface decisions needed

## Denylist

None yet.

## Evidence Trail

- **H1 (good-first-issue label)**: #45 was labeled and had clear scope
- **H2 (mechanical acceptance)**: Search feature has concrete pass/fail - either filtering works or it doesn't
- **H3 (bug fixes over features)**: N/A - this is a feature, but maintainer explicitly labeled as good-first-issue
- **Quality gates**: Both codex and gemini passed. Gemini caught perf issue (allocating search query string per iteration).

## Next Steps

1. Monitor drip queue for #45 PR merge/close
2. If merged: Consider #17 (tree visualization) or #7 (dynamic analysis options)
3. If closed without merge: Extract lessons, update hypothesis weights
