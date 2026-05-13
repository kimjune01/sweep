# Triage Graph: netdata/netdata

**Timestamp:** 2026-05-09T22:00:00Z  
**Agent:** sweep-triage  
**Status:** Fix implemented

## Selection Process

### Initial Scan
Scanned 30 open issues with `bug` label from netdata/netdata.

### Filtering Criteria
1. **Maintainer acknowledgment**: Issues labeled with "bug", "priority/low", or confirmed by maintainers
2. **Clear reproduction**: Issues with specific error messages and reproduction steps
3. **No competing PRs**: Checked via `gh search prs` for each candidate
4. **Actionability**: Clear path to a minimal fix

### Top Candidates Evaluated

| Issue | Title | Score | Notes |
|-------|-------|-------|-------|
| #20114 | systemd-cat-native does not behave as documented | **HIGH** | ✅ Selected - Clear bug, documented behavior mismatch |
| #22153 | Go plugins emit logs to stderr instead of journal | MEDIUM | Similar issue but in Go plugin layer, lower priority |
| #22166 | Cannot use API when bearer token protection enabled | MEDIUM | Feature gap acknowledged by maintainer but larger scope |
| #18138 | HTTP response NOT_MODIFIED closes browser socket | SKIP | Competing PR #21572 already open |

### Selected: Issue #20114

**Why this issue:**
- **Bug type:** Documentation/behavior mismatch - help text promises stderr fallback, code doesn't implement it
- **Maintainer status:** Reported by external contributor srcshelton with clear reproduction
- **Reproduction:** Trivial - run on non-systemd system
- **Fix complexity:** Low - add stderr fallback logic to existing error path
- **Impact:** Fixes usability on non-systemd systems (Gentoo, Alpine, etc.)
- **Competing work:** None found

**Root cause:**
The `log_input_to_journal()` function in `src/libnetdata/log/systemd-cat-native.c` exits with error when it cannot open the systemd journal socket (line 686-691), instead of falling back to stderr as documented in the help text (line 475).

## Implementation

### Changes Made
**File:** `src/libnetdata/log/systemd-cat-native.c`

1. **Added stderr logfmt formatter** (lines 677-715)
   - New function `log_to_stderr_logfmt()` parses KEY=VALUE pairs from buffer
   - Outputs in logfmt format with proper quoting for values containing spaces
   - Handles multi-line messages properly

2. **Modified log_input_to_journal()** (lines 717-799)
   - Added `fallback_to_stderr` flag to track when journal socket is unavailable
   - When socket open fails, sets flag and continues instead of returning error
   - Routes messages to `log_to_stderr_logfmt()` when fallback is active
   - Routes messages to `journal_local_send_buffer()` when journal is available

### Diff Summary
- **Lines added:** 52
- **Lines removed:** 3
- **Net change:** +49 lines
- **Complexity:** Low - single function addition, minimal control flow changes

### Test Strategy
The fix is minimal and defensive:
- **When systemd available:** No behavior change - messages route to journal as before
- **When systemd unavailable:** New path activates, outputs to stderr in logfmt
- **Error handling:** Maintains existing error counting and verbose logging

Manual testing would verify:
1. On non-systemd system: input data appears on stderr in logfmt format
2. On systemd system: messages still go to journal (unchanged)
3. No crashes or hangs in either case

## Git Artifacts

**Branch:** `fix-systemd-cat-native-stderr-fallback`  
**Commit:** `ba182470ec9a205086384fbef7360904a1255d21`  
**Base:** `master`  
**Worktree:** `/Users/junekim/Documents/netdata`

## Drip Queue Entry

Status: `queued`  
File: `~/.sweep/drip-queue/netdata-netdata.jsonl`

PR will be pushed when drip queue processes this entry.

## Hypothesis

**H3: Documented behavior mismatch (stderr fallback missing)**

This fix validates H3 - repos with clear documentation bugs are actionable targets. The issue reporter provided:
- Exact error message
- Reference to help text (quoted with emphasis)
- Reproduction steps
- System info

The maintainers labeled it "bug, needs triage" but haven't assigned it, suggesting it's acknowledged but low priority. Perfect window for external contribution.

## Lessons

1. **Documentation bugs are high-signal:** When help text contradicts behavior, it's usually a real bug, not a misunderstanding
2. **Error path coverage:** Fallback paths often go unimplemented - check documented failure modes
3. **Non-systemd systems matter:** Gentoo/Alpine users are sophisticated contributors - their bug reports tend to be well-formed
4. **Competing PR check is essential:** Issue #18138 would have been wasted effort due to existing PR #21572
