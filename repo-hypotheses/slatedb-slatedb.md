# slatedb/slatedb Triage Graph

## Investigated

### #1581 - Merge ops with different TTLs dropped
- **Status**: Investigated, failing test added, no fix
- **Complexity**: HIGH - requires oracle sequence range reservation
- **Findings**: 
  - Initial fix (seq + write_idx) breaks oracle allocation, snapshot visibility, sequence semantics
  - Proper fix needs: reserve contiguous seq range, assign per-entry seqs, advance all metadata to range end
  - Architectural change beyond scope of initial triage
- **Branch**: abandoned (committed failing test to document bug)
- **Recommendation**: Needs maintainer design discussion

### #1542 - DbReaderBuilder bypasses DbCacheWrapper
- **Status**: FIXED
- **Complexity**: LOW - one-line fix matching DbBuilder pattern
- **Findings**:
  - DbReaderBuilder passed cache unwrapped → all readers at scope_id=0 → cross-DB corruption
  - Fix: wrap cache in DbCacheWrapper before passing to DefaultStoreProvider
  - Test: test_db_reader_cache_scoping validates isolation
  - Codex noted pre-existing bug: first wrapper gets scope_id=0 (should start at 1)
- **Branch**: fix-dbcache-wrapper-bypass
- **Commit**: 40e38a0
- **Ready**: Yes, pending drip queue

## Skipped

### #1640 - Low flush_interval creates too many manifests
- PR #1639 already open (makes MAX_WAL_FLUSHES_BEFORE_L0_FLUSH configurable)
- Issue is about better defaults, not just configurability
- Defer to maintainer preference

### #1636 - Support temporary memtables for DbReader  
- RFC required (label: rfc)
- 2 comments with design discussion
- Too large for initial contribution

### #1627 - Cache compacted SSTs
- Enhancement, no mechanical acceptance criteria
- Needs maintainer buy-in first

### #1622 - slatedb can lose flushed writes
- 7 comments with detailed analysis
- Dupe of #352
- Active maintainer investigation
- Wait for maintainer fix direction

### #1598 - Support Leveled Compaction
- Large feature (already has assignee)
- Not suitable for external contribution

## Hypothesis Updates

- **H2 (test-first acceptance)**: #1542 validates this - small bug fix with clear test, clean merge path
- **H4 (maintainer-acknowledged problems)**: #1581 shows limits - acknowledged bug but fix requires architectural changes
- **H5 (competing PRs)**: #1640 had competing PR #1639, correctly skipped
