# Triage Graph: fjall-rs/fjall

Solo maintainer Rust LSM-tree storage engine. First contribution targeting smallest actionable issue.

## Issues Investigated

### #183 - Hang when Database dropped with live Keyspace handles ✅ SELECTED

**Status**: Implementation complete, ready for drip queue  
**Labels**: documentation, enhancement, help wanted, good first issue, api  
**Actionability**: HIGH - Clear problem, maintainer acknowledged, documentation fix  
**Scope**: Small - docs + runtime warning  

**Problem**: When Database is dropped while Keyspace handles exist, background worker threads stop, causing write operations to hang indefinitely. Silent deadlock, hard to debug.

**Solution implemented**:
1. Comprehensive lifetime documentation on Database struct with examples
2. Runtime warning in Database::drop when keyspace handles leak  
3. Clear journal_manager before strong_count check to avoid false positives
4. Updated Keyspace docs to reference Database lifetime requirements

**Reviews**:
- Codex (GPT-5.5): Approved after fixing journal_manager ordering and documentation precision
- Gemini 3.1 Pro: LGTM - logic sound, lock handling safe, noted potential rare false positive from background workers (acceptable)

**Branch**: fix-183-keyspace-drop-hang  
**Commit**: 2b8e0a0

### #288 - Idle keyspaces leads to unbounded sealed journals

**Status**: SKIPPED - Too complex for first contribution  
**Labels**: bug, help wanted  
**Issue**: Complex concurrency bug in journal system. User has partial patch but uncertain about correct fix.  
**Scope**: Large - requires deep understanding of journal/memtable lifecycle

### #287 - Concurrent clear() and ingestion API causes crash

**Status**: SKIPPED - Too complex for first contribution  
**Labels**: bug, help wanted  
**Issue**: Race condition leading to assertion failure and corruption  
**Scope**: Large - concurrency bug requiring careful synchronization

### #276 - Memory spike on cold start with 1M+ keys

**Status**: SKIPPED - Requires profiling/investigation  
**Labels**: performance  
**Issue**: Complex memory profiling issue with back-and-forth discussion  
**Scope**: Large - performance investigation, not mechanically actionable

### #271 - Snapshot/non-serialisable reads in OptimisticTxDatabase

**Status**: SKIPPED - Feature request, no discussion  
**Labels**: enhancement, api  
**Issue**: Clean feature request but no maintainer feedback yet  
**Scope**: Medium - API addition

### #262 - Feature request: get KeyspaceCreateOptions for keyspace

**Status**: SKIPPED - Maintainer confirmed breaking change  
**Labels**: enhancement, help wanted, good first issue, possibly breaking, api  
**Issue**: Maintainer already committed to 4.x branch, marked as breaking change for 3.x  
**Scope**: Small but blocked - already addressed in different version

### #233 - Guard::into_inner_if_some

**Status**: SKIPPED - Dependency on lsm-tree PR  
**Labels**: enhancement, help wanted, good first issue, api  
**Issue**: Has existing PR in lsm-tree dependency (#233)  
**Scope**: Small but dependency-blocked

### #212 - MUTANTS! (mutation testing)

**Status**: SKIPPED - Long-term incremental work  
**Labels**: help wanted, good first issue, test  
**Issue**: Huge list of mutation test failures, good for incremental contributions but not clear single unit of work  
**Scope**: Incremental - not a discrete first contribution

### #140 - Create zerocopy example

**Status**: SKIPPED - Already in progress  
**Labels**: help wanted, good first issue, examples  
**Issue**: Someone (databfnk) already working on it as of Sept 2025  
**Scope**: Small - example code

## Selection Rationale

**#183** selected as optimal first contribution:
1. ✅ Tagged "good first issue", "help wanted", "documentation"
2. ✅ Clear, well-defined problem with maintainer acknowledgment
3. ✅ Smallest scope - pure documentation + diagnostic warning
4. ✅ No competing PRs
5. ✅ Maintainer explicitly suggested documentation OR error handling as fix
6. ✅ Tests well under codex + gemini review (double-checked logic)

All other issues either too complex (#288, #287, #276), blocked (#262, #233), or already claimed (#140).

## Hypothesis Validation

**H0 (Good first issues are actually first-issue-friendly)**: SUPPORTED  
- #183 was marked "good first issue" and was indeed appropriate in scope
- #262 was marked "good first issue" but blocked by version constraints
- Other "good first issue" tags (#212, #140, #233) had valid reasons for skipping

**H1 (Documentation/error-message PRs merge faster)**: TO BE TESTED  
- #183 is pure docs + diagnostic warning, no behavior change
- Will measure merge time vs feature PRs

**H2 (Solo maintainers prefer small, self-contained PRs)**: TO BE TESTED  
- fjall is solo-maintained (marvin-j97)
- #183 is self-contained, requires no follow-up work

## Next Steps

1. ✅ Implementation complete
2. ✅ Reviews complete (codex + gemini)
3. ✅ Commit written
4. ✅ Drip queue entry created
5. ⏸️ WAIT - Do NOT push PR yet (drip queue will handle)

## Learnings

1. **Codex caught Arc reference counting edge case** - JournalManager holds Keyspace references via EvictionWatermark, needed to clear before strong_count check
2. **Gemini noted rare false positive from background workers** - acceptable tradeoff vs silent hang
3. **Issue #183 age**: Opened Aug 2025, still open May 2026 - 9 months stale but actively discussed by maintainer in comments
