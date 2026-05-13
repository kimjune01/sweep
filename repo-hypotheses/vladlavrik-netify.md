# Triage Graph: vladlavrik/netify

**Repo**: vladlavrik/netify  
**Stars**: 249  
**Language**: TypeScript  
**Description**: Chrome extension to intercept and modify network requests  
**Open Issues**: 11 (actually 9 issues, some discrepancy in count)  
**Date**: 2026-05-11 (updated 2026-05-11 post-triage)

## Maintainer Profile

- **Solo maintainer**: vladlavrik (85%+ of commits)
- **External PRs**: 4 merged historically
- **Responsiveness**: Active, responds to issues within days to weeks
- **Stance**: Helpful, provides debugging guidance, acknowledges bugs but doesn't always fix them quickly

## Issue Analysis

### Investigated

**#31 - Build Documentation** ✅ FIXED
- **Type**: Documentation gap
- **Status**: Fixed on branch `fix/build-documentation-31`
- **Approach**: Added comprehensive build instructions to README
  - Prerequisites (Node.js 18+)
  - Dev and production build commands
  - Chrome extension loading instructions
  - Troubleshooting for OpenSSL error
- **Evidence**: Maintainer provided instructions in comment but had typos (`npm build dev` → `npm run dev`), no docs in README
- **Risk**: Low - pure documentation addition
- **Standing Strategy**: Small, helpful, clearly beneficial

### Analyzed but Not Fixed

**#44 - Scripting console.log and response-only request logging** 🔍 COMPLEX
- **Type**: Two bugs acknowledged by maintainer (Jan 2024)
  1. console.log in sandbox doesn't show (needs feature, large scope)
  2. Response-only script rules don't appear in Network log (BUG - investigated 2026-05-11)
- **Status**: Acknowledged but not fixed after 15+ months
- **Complexity**: High - requires understanding:
  - FetchDevtools vs RequestListener event flow (parallel event streams)
  - RequestId vs NetworkId usage (CDP protocol details)
  - Log entry merging logic (NetworkLogsStore.addLogEntry)
  - Chrome DevTools Protocol nuances
- **Root cause hypothesis** (bug #2):
  - RequestListener emits `requestsInitialized` with `requestId`
  - FetchDevtools emits `requestProcessed` with `networkId || requestId`
  - If networkId differs from requestId, NetworkLogsStore.addLogEntry creates TWO entries:
    - One without modification (from RequestListener, requestId)
    - One with modification (from FetchDevtools, networkId)
  - If `networkLogOnlyAffected` filter is enabled, only modified entry shows
  - But requestId/networkId mismatch prevents proper merging
  - Fix requires: confirm CDP ID semantics, align ID usage in log emission, add tests
- **Standing assessment**: Too complex for first contribution, needs codex review + test infrastructure

**#22 - Empty Rules Panel** ❌ SKIP
- 15 comments, extensive debugging, maintainer can't reproduce
- IndexedDB access issue, environment-specific
- Not actionable without user reproduction

**#40, #33 - Panel Not Showing (Brave/Edge)** ❌ SKIP
- Maintainer can't reproduce
- Likely user environment or conflicting extensions
- Not clearly a Netify bug

**#17 - iframe Request Logging** ✅ WORKS AS DESIGNED
- Maintainer confirmed it works, just need full URL with protocol/hostname
- Documentation issue, not a bug

**#39 - Latency Option Missing** ❓ CLARIFICATION NEEDED
- Maintainer showed delay feature exists
- Waiting for user clarification

**#23 - Firefox Port** 🎯 FEATURE REQUEST
- Requires Firefox WebExtension APIs
- Large scope, not suitable for first contribution

**#42 - Share Custom Rules** 📚 ANSWERED
- Maintainer pointed to playground with example ruleset
- Not actionable

## Repository Structure

- **No CONTRIBUTING.md** - No formal contribution guidelines
- **No tests** - No test infrastructure found
- **Build system**: webpack, TypeScript
- **Structure**:
  - `src/` - TypeScript source
  - `build/` - webpack output
  - `playground/` - test server with example rules
  - Services: FetchDevtools (request interception), RequestListener (network events), Sandbox (script execution)

## Standing Assessment

- **Trust level**: 0 (new contributor)
- **Strategy**: Start with low-risk documentation fix (#31)
- **Earning path**: 
  1. Docs fix merges → establishes competence
  2. Small bug fix (if one emerges) → establishes technical skill
  3. Larger feature/refactor → full trust

## Queued Work

1. **fix/build-documentation-31** - Ready for review
   - Addresses #31
   - Pure documentation, no code changes
   - Verified build works locally
   - Status: Branch exists, committed, in drip queue

## Investigation Summary (2026-05-11)

- **Total open issues**: 9
- **Fully investigated**: 9
- **Actionable now**: 1 (#31 - build docs, already queued)
- **Requires codex review**: 1 (#44 - response-only logging bug, hypothesis documented)
- **Not actionable**: 7 (can't reproduce, answered, feature requests, clarification needed)
- **Next action**: None - all open issues triaged, one fix queued

## Hypotheses

- **H0 (demand)**: ✅ Confirmed - User explicitly asked for build docs
- **H1 (supply)**: ✅ High - Solo maintainer likely appreciates help
- **H2 (technical)**: ✅ Straightforward - Verified build process works
- **H3 (social)**: 🟡 Unknown - No PR history for this contributor
- **H4 (structural)**: ✅ Good - Clean TypeScript codebase, modern tooling
- **H5 (timing)**: 🟡 Medium - Issue is 1.5 years old but still relevant
- **H6 (complexity)**: ✅ Low - Pure documentation addition

## Next Steps

1. Push branch to fork (when ready to submit)
2. Create PR referencing #31
3. Monitor for maintainer feedback
4. If merged, consider investigating #44 (response-only logging bug) with full codex/gemini review cycle
