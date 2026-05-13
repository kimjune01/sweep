# Triage Graph: PyCQA/bandit

**Hypothesis**: H3 — Python security linter, PyCQA ecosystem (same org as pylint), bug-fix domain
**Date**: 2026-05-09
**Status**: QUEUED

## Repository Context

- **Organization**: PyCQA (Python Code Quality Authority)
- **Project**: bandit - Security linter for Python
- **Ecosystem**: PyCQA (pylint, flake8, bandit share maintainers/community)
- **Activity**: Active - recent commits, responsive maintainers
- **License**: Apache-2.0

## Issue Selection

### Scanned Issues (30 open)

Promising bug-fix issues:
1. **#1405** - B704 false negative for local Markup subclasses (CVE) - ASSIGNED to another contributor
2. **#1395** - B104 misses `bind(("", port))` wildcard - 2 closed PRs with CHANGES_REQUESTED
3. **#1394** - B501 misses verify=False on Session/Client instances - ✅ **SELECTED**
4. **#1392** - B202 unsafe tarfile.extract() not detected - 1 closed PR
5. **#1390** - B103 misses stat module constants - 1 closed PR
6. **#1383** - B105/B106/B107 hardcoded password FN - has competing PR #1385

### Selection Rationale: #1394

**Why #1394:**
- Clear false negative with reproduction case
- No competing PRs (unlike #1395, #1392, #1390)
- Maintainer-acknowledged (bug label)
- Fits bug-fix pattern (detection gap, not new feature)
- Same pattern as B113 timeout check (proven acceptable pattern)

**Risk factors:**
- No competing PRs might signal complexity (but repro is straightforward)
- Previous attempts on #1395 failed review (but different issue)

## Implementation

### Branch: `fix-b501-session-verify-false`
### Commit: `027d47e`

**Problem**: B501 only checks `qualname.startswith("requests")` or `"httpx"`, which misses:
- `session.get(..., verify=False)` where session = requests.Session()
- `requests.Session().get(..., verify=False)` chained calls
- `httpx.Client().get(..., verify=False)` chained calls

**Solution**:
1. Early return if `verify=False` not present
2. Check module-level calls (existing behavior): `requests.get()`, `httpx.get()`
3. Check chained calls: `*.Session.get()`, `*.Client.get()`, `*.AsyncClient.get()`
4. Catch-all: any HTTP verb method with `verify=False` (MEDIUM confidence)

**Confidence levels**:
- HIGH: Module-level calls (can verify from qualname)
- MEDIUM: Instance methods (can't statically verify variable type)

### Files Changed

1. **bandit/plugins/crypto_request_no_cert_validation.py**
   - Restructured detection logic to handle instance methods
   - Added three-tier detection (module, chained, catch-all)
   - Adjusted confidence levels appropriately

2. **examples/requests-session-verify-disabled.py** (new)
   - Documents newly detected patterns
   - Provides test cases for manual verification

### Test Results

**Existing tests**: ✅ All 95 functional tests pass
**Manual verification**:
- `examples/requests-session-verify-disabled.py`: 8 issues detected (correct)
- `examples/requests-ssl-verify-disabled.py`: 18 issues detected (unchanged)

## Competing Work

**GitHub search for existing PRs**: None found for #1394

**Related failed PRs**:
- #1396, #1400: Attempts at #1395 (different issue) - both CHANGES_REQUESTED
- #1393: Attempt at #1392 - CLOSED
- #1391: Attempt at #1390 - CLOSED

All three by same author (9iang22), all closed same day (2026-05-01). Possible batch-close event.

## Gate Check: PyCQA Org Pacing

**Question**: Does PyCQA enforce org-level PR limits?

**Evidence**: pylint PR search returned empty (memory mentioned #11002 but not found open)

**Action**: Proceed with queue - no evidence of org-level blocks

## Next Steps

1. **Drip queue entry**: ✅ Written to `~/.sweep/drip-queue/PyCQA-bandit.jsonl`
2. **Wait for drip**: Let /drip push when queue allows
3. **Monitor**: Watch for maintainer feedback on detection approach

## Lessons

- PyCQA has engaged maintainers (ericwb commented on #1395)
- Failed PR history suggests review rigor (good signal for landing value)
- Instance method detection requires confidence calibration (HIGH vs MEDIUM)
- catch-all with MEDIUM confidence balances coverage vs false positives
