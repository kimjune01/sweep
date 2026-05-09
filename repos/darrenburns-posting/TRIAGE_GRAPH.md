# Triage Graph: darrenburns/posting

**Hypothesis:** H2/H5 — Python TUI built with Textual, solo maintainer, 8 open PRs, 11.9K stars  
**Date:** 2026-05-09  
**Status:** 1 fix implemented, queued for drip

## Repository Overview

- **Stars:** 11.9K
- **Language:** Python (Textual TUI framework)
- **Maintainer:** darrenburns (solo)
- **Open PRs:** 8
- **Open Issues:** ~50

## Issue Scan Results

### Actionable Bug Found

**Issue #309:** Inconsistency: `curl` export format incompatible with `curl` import  
- **Reporter:** lawrence3699 (2025-12-31)
- **Status:** Open, no maintainer response
- **Competing PRs:** #349 (closed without merging, no comments)

**Problem:** When Posting exports a curl command, it places flags like `--cookie` before the URL. When importing that same command, the argparse parser doesn't recognize these flags and treats them as positional arguments, causing the URL to be misparsed.

**Evidence:**
```bash
# Exported by Posting:
curl --cookie 'AEC=...' --cookie 'logged_in=no' 'http://google.com'

# Imported URL (before fix):
"AEC=..." (first cookie value parsed as URL)

# Expected URL:
"http://google.com"
```

**Fix:** Add `--cookie`, `--location`, `--no-location`, and `--proxy` to the argparse parser in `src/posting/importing/curl.py`. This mirrors the approach from PR #349.

**Tests:** 4 new regression tests added to `tests/test_curl_import.py`, all passing.

### Other Issues Investigated

**Issue #292:** Can't use query parameters as References in path endpoints  
- **Status:** Already fixed in main (commit 5db2d5e2, 2026-03-25)
- **Action:** None — issue should be closed by maintainer

**Issue #269:** BASE_URL environment variable not working  
- **Status:** Fixed in v2.7.0 (maintainer comment)
- **Action:** None

**Issue #272:** File .env charged but variables not working  
- **Status:** Not a bug — UX issue (use Query tab instead of URL bar)
- **Maintainer response:** "we just need to improve the UI"

**Issue #237:** Failed to export cURL on MacOs Tmux  
- **Status:** Competing PR #268 closed with maintainer saying "needs config option"
- **Action:** Skipped — maintainer wants different approach

**Issue #325:** Client certificate options seemingly ignored  
- **Status:** No maintainer response, complex SSL issue
- **Action:** Skipped — needs deep investigation

**Issue #229:** Ctrl+D and Ctrl+U in read-only TextArea  
- **Status:** Filed by maintainer but no body/description
- **Action:** Cannot implement without acceptance criteria

**Issue #235:** Can't define query parameters as an array of objects  
- **Status:** Complex nested parameter support — feature gap, not clear bug
- **Maintainer:** Asked for clarification multiple times

## Hypothesis Evaluation

**H2 (Textual ecosystem):** Confirmed — built with Textual, shares ecosystem with other TUI projects  
**H5 (Solo maintainer):** Confirmed — darrenburns is the sole active maintainer

**PR velocity:** Slow. PR #268 closed without comment, PR #349 closed without comment. This suggests either:
1. Maintainer is busy and not reviewing external PRs regularly
2. PRs don't meet quality bar but feedback isn't provided

**Issue triage:** Most issues lack maintainer labels or acknowledgment. Bug label exists but rarely applied. No "good first issue" or "help wanted" labels.

## Implementation

**Branch:** `fix-curl-import-cookies`  
**Files changed:**
- `src/posting/importing/curl.py` — added argparse flags
- `tests/test_curl_import.py` — added 4 regression tests

**Test results:** 25/25 tests passing

**Commit message:** Links to issue #309, explains the problem, notes PR #349 precedent

## Next Steps

1. Branch queued in `~/.sweep/drip-queue/darrenburns-posting.jsonl`
2. Wait for /drip to push as PR
3. Monitor for maintainer response
4. If no response in 2 weeks, this validates "cold repo" hypothesis

## Lessons

1. **Closed PRs are signals:** PR #349 attempted the same fix but was closed without comment. This could mean:
   - The PR was low quality (no tests, poor explanation)
   - Maintainer wants a different approach
   - Maintainer is overwhelmed and closing without review
   
   Our implementation includes comprehensive tests and clear commit message to differentiate.

2. **Issue age vs actionability:** Older issues (2025) have more maintainer engagement than recent ones (2026), suggesting maintainer bandwidth has decreased.

3. **Test coverage matters:** The fix is trivial (4 lines), but 48 lines of tests demonstrate thoroughness.
