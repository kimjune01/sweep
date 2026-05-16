# litestar-org/litestar Triage Graph

Last updated: 2026-05-09

## Selected: #3013 - Bug: AbstractSecurityConfig sets security for all paths

- **Status**: Branch pushed (`fix/3013-security-exclude-openapi`), ready for PR via drip
- **Type**: Bug fix (OpenAPI spec correctness)
- **Competition**: None
- **Fix**: In `_openapi/path_item.py`, check `route_handler.opt.get("exclude_from_auth")` and set `security=[]` on the operation. This overrides root-level security per OpenAPI 3.1 spec.
- **Tests**: 1 new test added, all 173 security tests + 239 OpenAPI tests pass
- **Scope**: Handles `exclude_opt_key` case. Path-pattern `exclude` case requires handler to also set `opt={"exclude_from_auth": True}` (documented limitation).

## Evaluated and Rejected

### Contested (competing PRs exist)

| Issue | Competing PR | Status |
|-------|-------------|--------|
| #4489 Zizmor CI | #4490 (maintainer JacobCoffee) | Approved, stalled on SHA pinning |
| #4301 Remove contrib namespace | #4752/#4753/#4754 + #4730 + #4691 | Active work by maintainer + contributors |
| #3941 OpenAPI docs | #4641 (tysoncung) | Open, no reviews |
| #3450 FAQ/recipes | #4555 (maliktafheem) | Open |
| #3211 Code block line length | #4622 (Br1an67) | Open |
| #2077 root_path OpenAPI | #4625 (ndpvt-web) | Open |
| #1262 Rate Limit Config | #4654 (Hossam-Ismail) | Open |
| #4650 Optional Meta constraints | #4652 (temrjan) | Active review with provinzkraut |
| #4701 default_serializer dict copy | #4710 (Peopl3s) | Approved by sobolevn |
| #2467 Rename get_origin_or_inner_type | #4618 (Br1an67) | Open |

### Uncontested but Unsuitable

| Issue | Reason |
|-------|--------|
| #2548 Docs: latency benchmarks | Benchmark results don't exist anymore |
| #2118 JWT token revocation | Unclear spec, no maintainer guidance |
| #4617 structlog KeyValueRenderer | Deep structlog integration issue, may be upstream |
| #4296 AppConfig defaults mismatch | Broad refactor, high blast radius |
| #4399 pr_number_from_commit type | Maintainer said "don't bother, scheduled for removal" |
| #4466 OpenTelemetry hook type | OTel module being migrated (#4691), fix would be obsolete |
| #1272 CRUD generator CLI | Feature request, too large for first PR |
| #2015 Typing query keyword | 17 comments, complex design discussion needed |

## Repo Health Signals

- **Stars**: ~8K
- **Open PRs**: ~48 (high volume, many stale)
- **Maintainer activity**: provinzkraut and cofin active (reviewing within days)
- **sobolevn**: Active reviewer, quick turnarounds
- **CI**: Comprehensive (lint, type check, test matrix across Python versions)
- **Strategy**: Bug fixes merge. First-time contributor should target clear bugs with tests, not features.
