# Triage Graph: gitui-org/gitui

## Issue #1850: make branch_compare_upstream async

**Status**: READY FOR PUSH
**Branch**: async-branch-compare
**Commit**: 3549efad

### Problem
The synchronous `branch_compare_upstream` function calls `repo.graph_ahead_behind()`, which can be slow on large repositories (performance regression documented in #1845 for Linux kernel repo).

### Solution
Created AsyncBranchCompareJob following the established pattern from AsyncBranchesJob:
- New file: asyncgit/src/branch_compare.rs
- Added BranchCompare notification variant
- Exported from public API

### Review
- **Codex**: Provided complete implementation following codebase patterns
- **Gemini**: Flagged theoretical edge case in result() method that could destroy requests if called before run(). Analysis showed this is prevented by the AsyncSingleJob framework design - result() is only called on jobs retrieved via take_last(), which only returns completed jobs. Pattern is safe.
- **Tests**: All 167 asyncgit tests pass

### Implementation details
- Follows AsyncJob trait pattern
- Uses Arc<Mutex<Option<JobState>>> state machine
- JobState enum: Request → Response
- Returns AsyncGitNotification::BranchCompare on completion

### Next steps
Ready to push. First contribution to 21K star Rust TUI project.
