# Triage Graph: mike-engel/jwt-cli

Stars: 1468 | Language: Rust | Last pushed: 2026-05-11

## AI Policy
None stated. No CONTRIBUTING.md.

## Contributing Policy
No formal policy. Maintainer responsive but bandwidth-limited (7+ stale PRs open 1+ years).

## Issues Triaged

### #253 - Unsecured JWT (alg: none) [TRIAGED]
- **Type**: rfc_compliance (RFC 7519 Section 6.1)
- **Status**: Branch `fix/unsecured-jwt-253` pushed to fork
- **Mechanism**: jsonwebtoken library does not support alg:none (wontfix upstream). Bypassed for encode (manual base64url header.payload.) and decode (parse parts directly, skip signature validation).
- **Tests**: 3 tests (encode, decode RFC example, roundtrip)
- **Risk**: Medium. Made --secret optional (was required). New SupportedAlgorithms::None variant. translate_algorithm returns Option<Algorithm>.
- **Maintainer signal**: "if anyone would like to submit a PR, I'd be happy to review it" (2023). 2 thumbs up, 2 hearts on that comment.
- **Competing PRs**: None

## Issues Evaluated but Not Selected

### #162 - Secret in file format for RS256 [EVICTED]
- Competing PR #398 open 12 months, no review.

### #445 - Human-readable date format
- Already resolved by existing --date flag.

### #134 - Require --alg for validation
- Stale (2021), low priority.

### Multiple issues (402, 294, 277) - BLOCKED
- Waiting on upstream jsonwebtoken library support.
