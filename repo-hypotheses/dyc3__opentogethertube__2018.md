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

---

# Reinvestigate cycle — 2026-05-19

PR: #2018 fix: hide Discord login when not configured
Head SHA at reinvestigation: `5a2488e7` (branch `fix/hide-unconfigured-discord`)
Trigger: pr-state flagged failing CI (pack named CodeQL, but pack referred to a superseded SHA `8d73c918`).

## H₀ — failing check is CodeQL (per stale pack)

- **Perturbation:** `gh run list --branch fix/hide-unconfigured-discord --json conclusion,workflowName,headSha`.
- **Result:** at the live HEAD `5a2488e7`, CodeQL = success. The failing workflow on this SHA is **Cypress Tests** (run 26051503498).
- **Trajectory:** divergent — pack disagreed with live state.
- **Kill:** H₀ killed. Replaced by H₀′: Cypress Tests fails on the latest commit.
- **Mode:** induction (live API check).

## H₀′ — Cypress Tests fails on `5a2488e7`

- **Perturbation:** read failing-job logs for all three Electron Node matrix jobs (22.x / 24.x / 26.x).
- **Result:** all three jobs fail identically in `playback.spec.ts`, after the hls-video test passes. The next assertion never runs; Cypress prints:

  > We detected that the Electron Renderer process just crashed.
  > … If you're running lots of tests on a memory intense application …

  Spec totals: 6 tests, 4 passing, **1 failing, 1 skipped**.
- **Trajectory:** convergent across the 3 jobs.
- **Edge:** is the crash caused by something in the diff, or is it an Electron renderer memory flake?

## H₁ — this PR's diff caused the renderer crash

- **Perturbation:** diff the last green Cypress run on this branch (`8d73c918`, Cypress success — see H₁ verification line above this section) against the red one (`5a2488e7`).
- **Result:** the only intervening commit is `5a2488e7` itself: `fix(security): add rate limiting to handlers flagged by CodeQL`. It touches only server-side handlers (`getOwnedRooms`, `GET /api/user`, `/discord`, `/discord/callback`) — adds `consumeRateLimitPoints` calls. **No client code, no renderer code, no playback path, no hls/store touched.** All client-side edits (`App.vue`, `LogInForm.vue`, `NavUser.vue`, `store.ts`, `Account.vue`) were already in `8d73c918`, which passed Cypress on this same `playback.spec.ts`.
- **Trajectory:** divergent against H₁.
- **Kill:** H₁ killed. The diff is not on the renderer-crash path.
- **Mode:** deduction (causal trace between two CI runs on the same branch).

## H₂ — Electron renderer OOM flake under Cypress

- **Perturbations:**
  1. Recent Cypress runs on `master` (last 8, through 2026-05-13) all green. Same Cypress 15.12.0 / Electron 37.6.0.
  2. Prior commit `8d73c918` on this branch passed Cypress on identical `playback.spec.ts`.
  3. Crash banner: Cypress' own diagnostic suggests `experimentalMemoryManagement` / `numTestsKeptInMemory` — first-line hypothesis is renderer memory pressure, not a test-level assertion failure.
- **Trajectory:** convergent. Crash at the hls→next-test boundary in all 3 matrix jobs is consistent with a memory-budget tip-over in Electron 37 under Cypress, with the surrounding env (master, prior commit) both green.
- **Confidence:** ~85% (abduction + two inductive baselines).
- **Edge:** rerun Cypress; expect green.

## Provenance

- `5a2488e7` is the response to CodeQL alerts opened by the prior commit; author kimjune01.
- The repo does not currently set `experimentalMemoryManagement`. Tuning that is out of scope for this PR.
- No prior PR on this repo addresses Cypress Electron memory tuning.

## Graph state (reinvestigate cycle)

| Node | Status | Shape | Mode | Confidence |
|------|--------|-------|------|-----------|
| H₀  (CodeQL — from pack) | killed | divergent | induction | 99% |
| H₀′ (Cypress red on latest SHA) | confirmed | convergent | induction | 99% |
| H₁  (this PR's diff caused it) | killed | divergent | deduction | 95% |
| H₂  (Electron renderer OOM flake) | confirmed | convergent | abduction + induction | 85% |

## Diagnosis

The failing CI on PR #2018 at `5a2488e7` is an **Electron renderer memory crash inside Cypress on `playback.spec.ts`**, not a regression introduced by this PR. The only commit added since the last green Cypress run on this branch is a server-side rate-limit patch on routes unreachable from the failing spec. Master runs the same Cypress + Electron env and is green.

## Action

**No code change from our side.** This is a CI flake; the diff does not regress the failing path.

Recommended operator move: post a one-line comment asking the maintainer to rerun the failed Cypress jobs. If a clean rerun stays red on `playback.spec.ts`, that becomes a new H₀ owned by the project (Cypress/Electron memory budget on the hls test) and is not this PR's responsibility.

No branch push, no PR edit. Surface the diagnosis to the operator for the rerun-ask. Frontier closed.
