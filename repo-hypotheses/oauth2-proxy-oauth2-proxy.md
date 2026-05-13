# Triage Graph: oauth2-proxy/oauth2-proxy (kimjune01)

**Scan date:** 2026-05-09
**Language:** Go
**Default branch:** master

## Scan Table

| # | Title | Type | Score | Signal | Status |
|---|-------|------|-------|--------|--------|
| 1960 | [AlphaConfig] Some claims in OIDC token not accessible by ClaimSource | enhancement | 8/10 | good-first-issue, help-wanted, needs-tests, maintainer (JoelSpeed) confirmed | IN PROGRESS |
| 834 | More fields in /oauth2/userinfo | feature | 4/10 | Old, unclear scope | PENDING |
| 3340 | get displayName as claim from Microsoft Entra ID | support | 3/10 | User config question | PENDING |

## Selected Fix

**#1960** — Claims like `upn`, `given_name`, `family_name` from OIDC ID tokens are inaccessible via ClaimSource in alpha config headers because they are not automatically added to `AdditionalClaims`. Users must manually duplicate claim names into each provider's `additionalClaims` list.

**Fix:** `collectHeaderClaimsIntoProviders()` in `alpha_options.go` scans `InjectRequestHeaders` and `InjectResponseHeaders` for `ClaimSource` entries, skips built-in session fields (email, groups, access_token, etc.), and appends non-builtin claims to every provider's `AdditionalClaims` with deduplication. Called at the end of `MergeOptionsWithDefaults`.

**Branch:** `fix/auto-collect-header-claims`

### Competing PRs

| # | Title | State | Outcome |
|---|-------|-------|---------|
| 2685 | feat: allow arbitrary claims from IDToken/UserInfo to session state | closed | **Merged** (adds infrastructure) |
| 3348 | Pyodin/issue3340 | open | Different issue (#3340), unrelated |

PR #2685 was merged and added the `AdditionalClaims` field to providers. But it didn't add the auto-collection logic -- users still have to manually list claims in both places. Our fix closes the gap: if you reference a claim in a header, it's automatically added to `AdditionalClaims`.

### Maintainer Signal

JoelSpeed (maintainer) commented on #1960: "Not yet resolved, never got around to adding the additional claims support that I had intended to." This confirms the gap is acknowledged and the fix is wanted.

Issue labeled: enhancement, help wanted, good first issue, needs tests. The test suite uses Ginkgo -- our PR includes 7 test cases covering all edge cases.

### Risk

Low. The infrastructure (`AdditionalClaims`) already exists (merged via #2685). Our fix is additive -- it auto-populates what users currently configure manually. No behavior change for existing configs that already list claims in both places (dedup handles it).

## Repository Profile

- **Star count:** ~10k
- **Test framework:** Ginkgo/Gomega
- **Review speed:** Moderate (60-day stale bot active)
- **PR template:** Standard, no special requirements
- **Base branch:** master
