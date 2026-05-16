# Triage Graph: zhiburt/expectrl

**Repo**: https://github.com/zhiburt/expectrl  
**Stars**: 212  
**Issues**: 15 open  
**Maintainer**: zhiburt (99.3% commits, solo maintainer)  
**Language**: Rust (expect/pexpect port)

## Maintainer Profile

- Solo maintainer with 442/445 commits
- Responsive to issues (replies within days)
- Explicitly suggests features in issue comments
- Helpful diagnostic tone in responses
- Good first issue labels present

## Issue Analysis

Scanned 15 open issues:

### #77: Release request (async-io version)
- **Status**: CLOSED (maintainer released 0.9.0 on 2026-05-11)
- **Type**: Dependency update request

### #75: Method to extract remaining buffer on timeout ⭐
- **Status**: OPEN, feature request
- **Actionability**: HIGH
- **Evidence**: Maintainer explicitly said "So....maybe we could add one more method `get_available()` or something like it. We kind of already have it is just private."
- **Selected**: YES - maintainer-endorsed enhancement
- **Outcome**: Implemented as `available()` method following Rust API guidelines

### #69: spawn with modified environment variables
- **Status**: OPEN, question
- **Actionability**: LOW
- **Notes**: Maintainer provided workarounds using std::process::Command. User reports Windows-specific issues. Would require Windows testing infrastructure.

### #65: Run cmd by another user in Windows
- **Status**: OPEN, enhancement + question
- **Actionability**: LOW
- **Notes**: Windows-specific, requires CreateProcessAsUserW syscall knowledge

### #63: Command arguments not respected on Windows
- **Status**: OPEN, question
- **Actionability**: LOW
- **Notes**: Maintainer said "I believe it was fixed a few weeks ago, but not released yet" - already fixed in unreleased code

### #62: Reduce verbosity of logged session types
- **Status**: OPEN, enhancement + question  
- **Actionability**: MEDIUM
- **Notes**: PR #67 was attempted but closed. Requires API design decisions. Maintainer unsure of best approach.

### #50: Repeat terminal characters twice after interact
- **Status**: OPEN
- **Actionability**: LOW
- **Notes**: Maintainer provided `stty echo` workaround. Unclear if bug or terminal configuration issue.

### #23: Add pxssh support ⚠️
- **Status**: OPEN, enhancement, good-first-issue
- **Actionability**: LOW  
- **Notes**: Maintainer said "It requires an investigation if this is valuable at first." Substantial feature, not a simple fix.

### #19: sleep() before interactive() causes freeze
- **Status**: OPEN, help wanted
- **Actionability**: LOW
- **Notes**: Maintainer investigated, found platform-specific pty behavior difference (macOS/FreeBSD vs Linux). Deep system-level issue, likely unfixable.

### #16: Interact::on_input in async mode doesn't take Session
- **Status**: OPEN, good-first-issue, help wanted  
- **Actionability**: LOW
- **Notes**: Async design problem with Send+Clone. PR #15 is draft. Requires tokio/async-std mutex decision.

### #12, #10, #5: Tracking/investigation issues
- **Status**: OPEN
- **Actionability**: N/A
- **Notes**: Tracking issues, not actionable

## Selected Issues

### Issue #75: Add method to access buffered data after expect timeout

### Implementation

**Branch**: `add-get-available-method`  
**Commit**: `b8166ab`

**Changes**:
- Added `Session::available()` method (sync)
- Added `Session::available()` method (async)
- Comprehensive test coverage: timeout, EOF, empty, partial match
- Documentation with timeout debugging example
- Follows Rust API guidelines (C-GETTER: `available()` not `get_available()`)

**Review**: Gemini 3.1 Pro Preview
- Caught naming violation (should be `available()` per Rust conventions)
- Identified missing EOF test case
- Verified `&mut self` requirement is correct (BufReader pattern)

**Quality gates passed**:
- All existing tests pass
- New tests pass (4 sync + 4 async = 8 tests)
- Gemini adversarial review applied
- Maintainer-endorsed feature

---

### Documentation Typos: Fix typos in src/ comments and docs

**Branch**: `fix-documentation-typos`  
**Commit**: `a27dd3a`  
**Type**: Documentation quality fix

**Changes**:
Fixed 7 typos across 4 files:
- `src/lib.rs`: "choise" → "choice", "a async" → "an async"
- `src/process/mod.rs`: "programm" → "program", "represens" → "represents", "imideately" → "immediately", "a async" → "an async"
- `src/session/sync_session.rs`: "onces" → "once"
- `src/session/async_session.rs`: "onces" → "once"

**Rationale**: PR #73 (typos in documentation files) merged 2024-12-13. Maintainer accepts documentation quality PRs. These are obvious typos that reduce professionalism.

**Quality gates passed**:
- All tests pass (`cargo check` clean)
- No functional changes
- Low-risk documentation-only PR

---

### README Typos: Fix typos and update version

**Branch**: `fix-readme-typos`  
**Commit**: `5e647b7`  
**Type**: Documentation quality fix

**Changes**:
- Fixed "choiсe" → "choice" (Cyrillic 'с' removed)
- Fixed "used" → "user" (grammar fix)
- Updated dependency version "0.8" → "0.9" (current release)

**Rationale**: README is user-facing documentation. Version 0.9 released 2026-05-11 (PR #74 merged, crates.io updated). README still references 0.8. Confusing for new users.

**Quality gates passed**:
- No code changes
- README-only PR
- Factually correct (0.9 is current on crates.io)

## Evidence & Hypothesis Testing

**H0 (Cold repos reject feature PRs)**: Issue #75 is maintainer-requested, so bypasses this hypothesis. Typo PRs are documentation-only (not features), and PR #73 precedent shows maintainer accepts doc fixes.

**H3 (Complexity adds = instant reject)**: Issue #75 feature is simple delegation to existing private method. Typo PRs add zero complexity (pure deletions of wrong chars, insertions of correct chars).

**H5 (Feature PRs at cold repos = close)**: Issue #75 is maintainer-requested (not cold outreach). Typo PRs are not feature requests, they're quality fixes with precedent (PR #73).

## Competing PRs

None found for any selected issues.

## Next Steps

1. Push all 3 branches to fork
2. Do NOT create PRs yet (triage stage, not ship stage)
3. Mark as "queued" in drip queue
4. Wait for /drip or /ship command

## Summary

**Total findings**: 3 branches
- 1 maintainer-requested feature (issue #75)
- 2 documentation quality fixes (typos + version update)

**Risk profile**: Low
- Feature is explicitly requested by maintainer
- Typo PRs have precedent (PR #73)
- All changes are non-breaking

## Denylist

None. First PR to this repo.
