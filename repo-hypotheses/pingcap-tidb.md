# Triage Graph: pingcap/tidb (kimjune01)

**Scan date:** 2026-05-09
**Language:** Go
**Default branch:** master

## Scan Table

| # | Title | Type | Score | Signal | Status |
|---|-------|------|-------|--------|--------|
| 42770 | Panic in builtinRpadUTF8Sig.evalString | bug | 8/10 | good-first-issue, severity/minor, affects 6.1-7.1, clear panic trace | IN PROGRESS |

## Selected Fix

**#42770** — When `LPAD`/`RPAD` receive a targetLength near MaxInt64 (e.g. `4611686018427387904`), the multiplication `targetLength*4` overflows to a negative number, bypassing the existing guard `targetLength*4 > b.tp.GetFlen()`. This causes `strings.Repeat` to attempt an enormous allocation, panicking the server.

**Fix:** Add `targetLength > mysql.MaxBlobWidth` guard before the multiplication, matching the pattern used by `builtinSpaceSig` (line 897). Applied to both `builtinLpadUTF8Sig` and `builtinRpadUTF8Sig`. Test cases verify that `4611686018427387904` returns NULL.

**Branch:** `fix/lpad-rpad-overflow-panic`

### Codex Review Notes

Codex suggested also checking REPEAT and SPACE functions. Verified:
- **SPACE** already has `mysql.MaxBlobWidth` guard (line 897) -- no fix needed
- **REPEAT** already has `math.MaxInt32` cap (line 684) and `maxAllowedPacket` check -- no fix needed
- Only LPAD/RPAD UTF8 variants were missing the pre-multiplication guard

### Competing PRs

| # | Title | State | Age | Outcome |
|---|-------|-------|-----|---------|
| 43411 | expression: fix the bug of Rpad function | open | 3 years | Stale, only fixes Rpad (not Lpad), different approach, 12 comments with no resolution |

PR #43411 has been open since April 2023 with no merge. It only addresses Rpad, not Lpad. Our fix covers both functions with the same pattern and includes test cases for both.

### Risk

Low. The fix adds a short-circuit return before the overflow-prone multiplication. The guard value (`mysql.MaxBlobWidth = 16777216`) is already used by SPACE for the same purpose. No behavioral change for valid inputs -- MaxBlobWidth is 16MB, far above any practical pad length.

## Repository Profile

- **Star count:** ~38k
- **Merge rate for externals:** Moderate (many external PRs, active CI)
- **Review speed:** Variable -- some PRs reviewed within days, others stale for years
- **PR template:** Requires linking issue with "Issue Number:" line
- **Base branch:** master
- **CI:** Extensive (Bazel + Go test, multiple platforms)
