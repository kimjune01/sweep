# Triage Graph: tuono-labs/tuono

**Date**: 2026-05-09
**Hypothesis**: H4 -- Rust/React full-stack framework, test coverage gap
**Status**: READY -- Fix committed on branch `test/e2e-env-variables`

## Issue Analysis

### #634: Missing e2e tests for env variable loading (FIXED)

- **Type**: Test coverage, contribution opportunity
- **Severity**: Low -- no bug, but env var loading is untested
- **Competing PRs**: None
- **Fix complexity**: Low -- fixture + test additions

**Root cause**: Tuono supports `.env` file loading and `TUONO_PUBLIC_` prefix for client-exposed variables (via Vite's envPrefix), but this behavior has no e2e test coverage. Regressions in env loading would go undetected.

**Solution**:
1. `.env` fixture with `SERVER_TEST_VAR` and `TUONO_PUBLIC_TEST_VAR`
2. Rust route handler (`env-vars/index.rs`) using `std::env::var().unwrap_or_default()`
3. React page component with data-testid elements for both server and client vars
4. 3 Playwright tests: server-side env var, public var on server, public var on client

**Codex feedback applied**:
- Uses `unwrap_or_default()` instead of `expect()` to avoid panics in test fixtures
- Test structure follows existing e2e patterns in the repo

**Diff**: 4 new files, 22 lines added to existing test file
**Testing**: `cd e2e && npx playwright test`

## PR Viability: HIGH

**For**: Test-only PR. Tuono is early-stage, maintainers actively seek contributions. Tests fill an explicit gap. No behavioral changes.
**Against**: Framework is young -- CI may be flaky. Env var behavior may change before stable release.
