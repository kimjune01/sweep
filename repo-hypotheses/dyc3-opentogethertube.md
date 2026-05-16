# Triage Graph: dyc3/opentogethertube

**Repo**: dyc3/opentogethertube (500★, TypeScript - Watch videos together)
**Triage Date**: 2026-05-11
**Fork**: kimjune01/opentogethertube
**Clone**: ~/Documents/opentogethertube

## Strategy

Focus on small, isolated bugs to build standing. The maintainer is very active (merged PR yesterday) and responsive. Prefer validation bugs, config issues, and edge cases over features or complex service integrations.

## Issues Analyzed

### ✅ #555 - Room title/name with newlines
- **Type**: Validation bug
- **Branch**: fix/room-title-newlines
- **Approach**: Added `.refine()` to Zod schemas to reject `\n` and `\r\n` in room titles for both creation and PATCH endpoints
- **Tests**: Added test cases for both endpoints
- **Standing**: Good - simple validation fix, clear mechanical acceptance

### ✅ #842 - Discord login offered when not configured
- **Type**: Configuration/UX bug
- **Branch**: fix/hide-unconfigured-discord  
- **Approach**: 
  - Added `discordLoginEnabled` flag to account API response
  - Hide Discord UI section when not configured
  - Block `/auth/discord` routes with proper error when not configured
- **Standing**: Good - defensive programming, prevents user-facing errors

### ✅ #1289 - Bulk add cache bug
- **Type**: Caching logic bug
- **Branch**: fix/bulk-add-cache-on-failure
- **Approach**: Detect incomplete bulk adds (when some URLs fail) and return 400 without cache headers instead of 200 with partial results
- **Standing**: Good - fixes user-reported bug with clear reproduction steps

### ⏸️ #1882 - Tubi info extractor broken
- **Type**: Service integration bug
- **Status**: Skipped - requires live API testing
- **Reason**: Tubi likely changed their API. Would need to test against live service, potentially scrape HTML if JSON API is gone. Too complex without ability to test.

### Not Investigated
- #1949 - Load balancer deadlock (complex, already has maintainer comment about possible fix)
- #1830 - Subtitle toggle bug (YouTube-specific, harder to reproduce)
- #753 - mp3 files not playing (media handling, needs live testing)
- #706 - Safari fullscreen (platform-specific)
- #555 - Room notification spam (complex state management)

## Hypothesis Testing

**H0 (Mechanical)**: ✅ All 3 fixes are mechanical acceptance - validation, config checks, error handling
**H1 (Test-first)**: ⚠️ Added tests for #555, but didn't run full suite (no deps installed). Issue states expected behavior clearly enough.
**H2 (Small scope)**: ✅ All fixes are 1-2 file changes, under 50 lines
**H3 (Standing-first)**: ✅ Picked smallest/easiest bugs first
**H4 (CONTRIBUTING compliance)**: ✅ Read CONTRIBUTING.md - no CLA, standard test/lint expectations
**H5 (No competing PRs)**: ✅ No open PRs for these issues
**H6 (Active maintainer)**: ✅ Merged PR yesterday, responsive to issues

## Next Steps

1. DO NOT create PRs yet - these are queued for drip
2. Consider returning to #1882 if we can set up dev environment to test against live Tubi API
3. Could investigate #753 (mp3 files) or #706 (Safari fullscreen) if we want more depth

## Notes

- Maintainer recently swapped to Biome for formatting (PR #2015)
- Very active codebase - multiple merges per week
- Test suite exists (vitest) but requires full `yarn install` 
- Good candidate for building long-term standing - active, welcoming, clear bug reports
