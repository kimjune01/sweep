# Triage Graph: sourcefrog/conserve

**Repository**: sourcefrog/conserve  
**Stars**: 277  
**Language**: Rust  
**Maintainer concentration**: 98% (sourcefrog: 2746 commits)  
**Open issues**: 47  
**Strategy**: Standing-first (solo maintainer, prefer smallest/easiest issues)

## Session: 2026-05-11

### Issue #115: Show source tree size in backup stats ✓
**Status**: Implemented  
**Branch**: fix-115-show-source-tree-size  
**Labels**: good-first-issue, size:small, topic:stats  
**Hypothesis**: H1 - Standing first with solo maintainer via clean, tested contribution

**Analysis**:
- Good first issue tag, size:small  
- No competing PRs  
- Clear TODO in codebase (line 573 in src/backup.rs)
- Issue requested breakdown: all files, unchanged, new, modified

**Implementation**:
- TDD approach: failing test first, then fix
- Added 4 fields to BackupStats: `source_files_bytes`, `source_unchanged_files_bytes`, `source_new_files_bytes`, `source_modified_files_bytes`
- Track sizes in `copy_file()` method at all decision points
- Updated Display impl to show sizes after file counts
- Test covers: initial backup (all new), second backup (1 modified, 2 unchanged)
- All 21 backup tests pass

**Commits**:
1. d0c7d923 - test: reproduce #115 (fails on main)
2. 053fe296 - fix: #115 show source tree size in backup stats

### Issue #189: Better error when source doesn't exist ✓
**Status**: Implemented  
**Branch**: fix-189-better-source-error  
**Labels**: none  
**Hypothesis**: H1 - Standing first with UX improvement

**Analysis**:
- Error message quality issue affecting usability
- No competing PRs
- Clear problem: "no such file or directory" without path context
- Issue mentions `~` not expanded as triggering case

**Implementation**:
- TDD approach: write failing test, then fix
- Wrapped `fs::symlink_metadata()` error in `Iter::new()` with `Error::ListSourceTree`
- Error now shows: "Failed to read source tree \"/path/does/not/exist\": No such file or directory"
- Test verifies path is included and message indicates source problem
- All 8 source tests pass

**Commits**:
1. ac38bf77 - test: reproduce #189 (fails on main)
2. af9543be - fix: #189 better error when source directory doesn't exist

### Issue #114: Add stats for restore, analogous to backup ✓
**Status**: Implemented  
**Branch**: fix-114-restore-stats  
**Labels**: good-first-issue, size:small, topic:stats  
**Hypothesis**: H1 - Standing first with sister issue to #115

**Analysis**:
- Sister issue to #115 which we just implemented
- Same pattern: BackupStats already exists, need RestoreStats
- No competing PRs
- Clear scope: match what backup does

**Implementation**:
- TDD approach: write failing test first
- Created RestoreStats struct (files, symlinks, directories, file_bytes, errors, elapsed)
- Updated restore() to return Result<RestoreStats> instead of Result<()>
- Updated restore_file() to return bytes restored
- CLI now prints stats after restore (unless --no-stats)
- Updated one test that expected empty stderr to use --no-stats
- All 143 lib tests + 41 CLI tests pass

**Commits**:
1. b47397ff - fix: #114 add stats for restore
2. 91f0a699 - test: add --no-stats to permission test

## Denied Issues

None yet.

## Investigation Notes

### Codebase structure
- Core backup logic in `src/backup.rs`
- Source tree iteration in `src/source.rs` (lazy evaluation, error on iter)
- Stats in `src/stats.rs` (helper functions for display)
- Error types in `src/errors.rs` (thiserror-based)
- Tests use TreeFixture for filesystem mocking
- Async/await throughout (tokio)
- Clean separation: BackupWriter handles per-entry logic, backup() orchestrates

### Pattern learned
- Solo maintainer (sourcefrog) maintains high quality bar
- Good test coverage expected
- TDD approach fits well with this codebase culture
- SourceTree::open is lazy - doesn't validate path exists
- Actual filesystem access happens in Iter::new via symlink_metadata
- Error wrapping pattern: map_err to add context (path, operation)

### Issue #86: ls -l to show mtime and permissions ✓
**Status**: Implemented  
**Branch**: fix-86-ls-mtime  
**Labels**: type:feature, topic:ui, good first issue  
**Hypothesis**: H1 - Standing first with UI enhancement

**Analysis**:
- Good first issue tag
- Clear feature request: add mtime to ls -l output
- mtime already available in IndexEntry, just not displayed
- No competing PRs

**Implementation**:
- TDD approach: write failing test first
- Updated `format_ls` in EntryTrait to include mtime
- Format: `{mode} {owner} {mtime} {path}`
- Example: `rwxr-xr-x user group 2020-06-15 17:15:23 /path`
- Updated 4 test files to check for components rather than exact string matches
- All 143 lib tests + 42 CLI tests + 6 old_archives tests pass

**Commits**:
1. dc1e1a3e - fix: #86 show mtime in ls -l output

### Session summary
- 4 issues completed (#115, #189, #114, #86)
- All followed TDD: failing test, fix, all tests pass
- All ready for /drip → /ship
- Time: ~3 hours total
- Pattern: good-first-issue + size:small tags = reliable standing-builders

## Reinvestigate: 2026-05-18 (PR #300)

**Trigger**: attest re-entry routed to reinvestigate lane.
**Context pack**: 0 failing checks (none configured on `fix-115-show-source-tree-size`), no comments, no reviews, `MERGEABLE`, HEAD `053fe296` matches worktree.
**Attest adversary outputs**: both codex and gemini wrappers returned `<stub: ... not implemented>` — no real verdict drove the re-entry, no kill condition to mine.
**Perturbation surface**: empty. CI never ran (`gh pr checks 300` → "no checks reported"); maintainer hasn't engaged.

**Trajectory shape**: null perturbation → no classifiable trajectory. Not convergent, not divergent — there's no signal.

**Edge**: none. PR waits on maintainer attention; substrate action is to leave it in /drip's open-PR set and let pr-state pick it up when state changes. No code change, no new node.

**Halt**: frontier closed for this cycle. Re-enter only on (a) maintainer comment, (b) CI configured + red, or (c) real attest verdict (non-stub).
