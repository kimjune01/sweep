# Triage Graph: envoyproxy/envoy

**Timestamp**: 2026-05-09T19:55:00Z
**Branch**: sweep-triage-1778364683
**Issue**: #44111

## Issue Selection Process

### Candidates Evaluated

1. **#44924** - HTTP/1.1 header casing documentation reversed
   - Status: Has competing PR #44939
   - Skipped

2. **#44895** - Local rate limit stats documentation fix
   - Status: Has competing PR #44930
   - Skipped

3. **#44704** - Golang filter crash with SendLocalReply
   - Status: Has competing PR #44974, security issue
   - Skipped

4. **#44499** - data-plane-api sync failing
   - Status: No competing PRs, but unclear root cause
   - Investigated but deferred

5. **#44111** - Stateful session cookies incompatible between Envoy processes ✓
   - Status: No competing PRs, maintainer-acknowledged, clear fix
   - **Selected**

## Selected Issue: #44111

### Diagnosis

**Problem**: Cookie expiry timestamps use `monotonicTime()` which is process-specific. When requests are load-balanced across multiple Envoy instances, cookies created by one instance appear expired to another because their monotonic clocks differ.

**Root Cause**: Two locations in the code use `time_source_.monotonicTime()`:
- `cookie.cc:22` - setting cookie expiry when creating cookie
- `cookie.h:78` - validating cookie expiry when parsing cookie

**Maintainer Confirmation**: cpakulski acknowledged the bug and stated "Your analysis makes sense. I do not remember exact reasoning behind usage of monotonic time, but am thinking that the design process did not take 1+ Envoys into account."

### Solution Implemented

Changed both locations from `monotonicTime()` to `systemTime()`:

1. **cookie.cc line 22**: Cookie creation timestamp
2. **cookie.h line 78**: Cookie validation timestamp

This ensures all Envoy instances use wall-clock time that is synchronized across processes.

### Commit

- Branch: `sweep-triage-1778364683`
- Commit: `9f7eb14f`
- Files changed: 2
- Lines changed: 2 deletions, 2 insertions

### Risk Assessment

**Low Risk**:
- Minimal change (2 lines)
- Well-understood fix (clock source swap)
- Maintains existing behavior for single-instance deployments
- Fixes reported bug for multi-instance deployments
- No new dependencies or API changes

### Next Steps

1. Drip queue entry created
2. Ready to push to fork when drip slot opens
3. Will create PR referencing issue #44111
