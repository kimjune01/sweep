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

## PR #2018 — post-open investigation (2026-05-17)

CI signal: e2e (electron, 22/24/26) all FAIL with identical assertion:
`Timed out... Expected to find element: [data-cy="account-link-discord"]` (and `account-unlink-discord` ×2).
All other checks green. Master cypress on the same workflow is green.

### H₀: e2e failures are pre-existing flake
- **Perturbation**: compare run history on master for the Cypress Tests workflow.
- **Trajectory**: divergent against. Last 5 master runs all `success`. PR fails 3/3.
- **Verdict**: KILLED. The PR introduced the regression.

### H₁: Account.vue `v-if="account.discordLoginEnabled"` removes the buttons
- **Mechanism**: `client/src/views/Account.vue:35-79` wraps the entire Discord card (containing both `[data-cy="account-link-discord"]` and `[data-cy="account-unlink-discord"]`) in `v-if="account.discordLoginEnabled"`. The flag derives from `isDiscordLoginEnabled()` which requires `DISCORD_CLIENT_ID` and `DISCORD_CLIENT_SECRET` set to non-`NONE` values.
- **Perturbation**: read `.github/workflows/e2e.yml` — no Discord env vars set anywhere in the e2e job. The server boots with `discord.client_id = "NONE"`, helper returns `false`, card unmounts.
- **Trajectory**: divergent confirm. Mechanism explains all three failure messages on all three matrix entries.
- **Verdict**: CONFIRMED. Reasoning mode: deduction. Confidence: 98%.

### H₁ fix-shape options
- **A** — set dummy `DISCORD_CLIENT_ID=test-id` / `DISCORD_CLIENT_SECRET=test-secret` in `e2e.yml` env block. Mirrors `server/tests/unit/api/user.spec.ts:107-110` which uses the exact same dummy values via `conf.set`. No source-code change.
- **B** — gate the card via `v-show` or only hide the buttons. Defeats the UX intent of the PR.
- **C** — seed Discord config through a new dev endpoint. No such endpoint exists.

Picked A — matches existing convention, single-file workflow edit, no production code change.

### Applied
- `.github/workflows/e2e.yml`: added `DISCORD_CLIENT_ID: test-id` and `DISCORD_CLIENT_SECRET: test-secret` to the e2e job env block.

### Frontier
- Push, watch CI. If e2e flips green, request review.
- CodeQL FAILURE is unrelated to this PR's surface (.vue + .ts edits; no shell/SQL/injection). Inspect after e2e green.

## Re-entry 2026-05-17

Verified PR head `08908d05` (2026-05-14) — `.github/workflows/e2e.yml` does NOT contain DISCORD env vars. Prior "Applied" entry above was local-only and never pushed; the local clone at `~/Documents/opentogethertube` is gone. Diagnosis re-verified against current PR head:
- `client/src/views/Account.vue:35` still wraps the Discord card in `v-if="account.discordLoginEnabled"`.
- `tests/e2e/integration/account.spec.ts:89,90,164,185,187,188` directly query `[data-cy="account-link-discord"]` / `[data-cy="account-unlink-discord"]`.
- E2e on PR head still fails 3/3 matrix (22/24/26 electron); master e2e green; other checks green except CodeQL (orthogonal).

Plan: fresh clone of `kimjune01/opentogethertube` at `fix/hide-unconfigured-discord`, re-apply Fix A in `e2e.yml` env block, push, watch CI. Identical to original prescription — no new hypothesis.

### 2026-05-18 — pushed
- Fresh clone at `/tmp/ott-2018`.
- Added `DISCORD_CLIENT_ID: test-id` and `DISCORD_CLIENT_SECRET: test-secret` to the e2e job-level `env:` block in `.github/workflows/e2e.yml` (lines 93–96, alongside `SESSION_SECRET`/`CI`).
- Pushed `08908d0..8d73c91` to `kimjune01/opentogethertube fix/hide-unconfigured-discord`.
- Perturbation H₁ verification: watch the next Cypress Tests workflow run on PR #2018. Predicted classification: divergent confirm — e2e (22/24/26) flips to SUCCESS. If e2e remains red, the diagnosis is incomplete; split off the new failure mode as H₂.

## Next Steps

1. DO NOT create PRs yet - these are queued for drip
2. Consider returning to #1882 if we can set up dev environment to test against live Tubi API
3. Could investigate #753 (mp3 files) or #706 (Safari fullscreen) if we want more depth

## Notes

- Maintainer recently swapped to Biome for formatting (PR #2015)
- Very active codebase - multiple merges per week
- Test suite exists (vitest) but requires full `yarn install` 
- Good candidate for building long-term standing - active, welcoming, clear bug reports
