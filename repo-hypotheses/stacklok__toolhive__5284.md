# stacklok/toolhive#5284 — OIDC `--oidc-scopes` advertises but does not enforce

## H₀ — observation (issue author's claim)

> `--oidc-scopes` is named/documented like an enforcement knob but `validateClaims` in `pkg/auth/token.go` never consults `v.scopes`. Any token with valid iss/aud/exp is accepted regardless of `scope` claim.

**Perturbation**: read `pkg/auth/token.go` (grep `v.scopes`).
**Result**: confirmed by code inspection.
- `v.scopes` is stored from `config.Scopes` at line 701.
- Read sites: line 1156 (`buildWWWAuthenticate` — header advertisement) and line 1309 (`NewAuthInfoHandler` — `scopes_supported` metadata field). Both are advertisement-only.
- `validateClaims` (line 947–) checks iss/aud/exp only.
- No `scope` claim handling anywhere in the validator path.

**Trajectory**: divergent (against the documented behavior). H₀ confirmed.
**Mode**: deduction. **Confidence**: 99%.

## H₁ — fix shape: enforce scope claim in `validateClaims`

**Perturbation**: implement the issue's suggested fix verbatim with three additions:
1. New sentinel `ErrInsufficientScope`.
2. `validateClaims` checks every required scope is present in the space-separated `scope` claim (RFC 9068 §2.2.3 / RFC 8693 §4.2).
3. Middleware maps `ErrInsufficientScope` → 403 + `WWW-Authenticate: ... error="insufficient_scope"` per RFC 6750 §3.1 (the existing `OAuthErrInsufficientScope` constant was already defined but never reachable).
4. CLI flag description corrected.

**Result**: builds; targeted `pkg/auth` tests pass.

**Trajectory**: convergent. **Mode**: induction. **Confidence**: 92%.

## H₂ — RFC 8693 array form of `scope`

**Question**: some token issuers emit `scope` as a JSON array, not a space-separated string. Would the fix silently fail-open on those tokens (string assertion fails, `tokenScopes` empty, every required scope reported missing → tokens **rejected**, not accepted)?

**Perturbation**: trace the type assertion `claims["scope"].(string)` with non-string input.
**Result**: when `scope` is `[]any{"read"}`, the assertion fails and `scopeClaim` is `""`. `tokenScopes` is empty. The first required scope fails the `slices.Contains` check → `ErrInsufficientScope`. Fail-closed, which is the desired direction for a security fix.

**Trajectory**: convergent. **Mode**: deduction. **Confidence**: 98%.
**Edge**: array-form `scope` over-rejects (false negatives), but does not under-reject (no false positives). Acceptable for v1; maintainer can extend handling if real-world deployments use array form.

## H₃ — opaque-token introspection path (`introspectOpaqueToken` → `validateClaims`)

**Question**: does the fix also cover opaque tokens (RFC 7662 introspection)?
**Perturbation**: read `parseIntrospectionClaims` (line 1000) and the call site at line 1060.
**Result**: introspection responses map `scope` (string) into `claims["scope"]`. `validateClaims` runs the same scope check. Coverage extends naturally.

**Trajectory**: convergent. **Mode**: deduction. **Confidence**: 95%.

## H₄ — regression on existing tests with `Scopes` set

**Question**: are there pre-existing tests that configure `Scopes` and assume non-enforcement?
**Perturbation**: grep `Scopes:.*\[\]string` under `pkg/auth/`; the only enforcement-path uses are in the new test. The advertisement path (`TestBuildWWWAuthenticate_*`, `TestNewAuthInfoHandler`) builds validators with scopes but does not run `validateClaims`. No regressions.

**Trajectory**: convergent. **Mode**: induction. **Confidence**: 95%.

## Fail-on-master / pass-on-fix

`TestTokenValidator_RequiredScopes` references `ErrInsufficientScope`, which does not exist on master. Test slice cherry-picked onto master fails to compile (`undefined: ErrInsufficientScope`). Compiles + passes on fix branch. Verified locally in `sweep-tester:latest`.

## Frontier (open, not blocking)

- **Per-route scope policies**: this issue's scope is global (validator-wide). Per-route required scopes are a larger design change; out of scope.
- **`scope` as array claim**: behaves as fail-closed; if a real deployment hits it, a maintainer can split string vs `[]any` handling.

## Diff

```
 cmd/thv/app/common.go  |   3 +-
 pkg/auth/token.go      |  22 +++++++++-
 pkg/auth/token_test.go | 113 +++++++++++++++++++++++++++++++++++++++++++++++++
 3 files changed, 136 insertions(+), 2 deletions(-)
```
