# MCPJam/inspector Triage Graph

## Repo Context
- Stars: 1937 (200-500 star bucket dynamics apply, but this is larger)
- Top contributors: chelojimenez (1179), matteo8p (581), ignaciojimenezr (191)
- Not solo-maintainer: 3 active core contributors
- Conventional commits required, no CLA, no commit limit per PR
- Target branch: main
- Build: npm workspaces monorepo (mcpjam-inspector, sdk, cli, design-system, soundcheck, mcp)

## Active Fixes

### #1515 — Cannot run evals with Custom Provider only
- **Status**: TRIAGED (branch: fix/custom-provider-evals)
- **Root cause**: Eval runner only uses `useAiProviderKeys` (no "custom" slot) for credential checks, and server only gets customProviders from org runtime.
- **Fix**: Thread customProviders through full eval pipeline (client credential check + server RunEvalsRequestSchema + evals-runner plumbing)
- **Test**: Added test verifying custom provider configs reach createLlmModel
- **Competing PRs**: None

### #1823 — macOS desktop download returns 404
- **Status**: TRIAGED (branch: fix/docs-download-links)
- **Root cause**: docs/installation.mdx hardcoded v2.2.0 download URLs; that release has no assets
- **Fix**: Changed to /releases/latest/download/ pattern (matches README.md)
- **Competing PRs**: None

## Skipped (with reason)

### #1415 — Read Resource button location
- SKIP: Merged PR #1511 + open competing PR #1917

### #1604 — Elicitation dialog stuck open
- SKIP: Open competing PR #1919 (3 reviews, no maintainer review yet)

### #1956 — Tool output schema not passed to LLM
- SKIP: Two competing PRs (#1986, #1964)

### #1982 — Dark/light mode switch broken
- SKIP: Competing PR #1983

### #1435 — Electron port hardcoded
- SKIP: Competing PR #1460

### #1723 — Client secret 8-char minimum
- SKIP: Competing PR #1920

### #1593 — OAuth token refresh not triggered
- SKIP: PR #2052 merged for hosted mode; local-mode fix requires deep OAuth plumbing

### #1588 — Duplicate requests
- SKIP: React StrictMode double-renders effects in dev. Not a production bug.

### #947 — a11y div onClick
- SKIP: Only 2 instances remain, both are event delegation on content containers (intercepting relative link clicks in rendered markdown). Not semantically incorrect.

### #2071 — Network error
- SKIP: Collaborator already triaged with workaround (sign in). Auth flow issue.

### #1701 — Error thrown for Object schemas
- SKIP: Dosu bot misdiagnosed; unable to reproduce (prior triage)

### #1692 — File upload fails with data: scheme
- SKIP: PR #1304 (merged) added file/image upload support. May need retest on current version.

### #1579 — Custom MCP server overwritten after login
- SKIP: Auth flow state management issue. Requires deep investigation of login/guest server persistence.

### #1515 — Custom provider evals (already fixed above)

### #864 — Improve response formatting
- SKIP: Feature discussion, not a bug. Maintainer conversation ongoing.

### #1303 — Make error handling better
- SKIP: Too broad. No specific actionable fix described.

### #2023 — Windows app no longer shows tools
- SKIP: Version mismatch (v2.2.0 vs v2.4.3). Can't test/fix from macOS.

### #1891 — Security: auth bypass via Host header
- SKIP: Security issue. External contributor shouldn't touch without maintainer coordination.

### #1682 — Security audit findings
- SKIP: Marketing/spam for paid audit report. Not an actionable bug report.

### #1695 — "mcp" (no content)
- SKIP: No useful information in the issue body.

## Denied Issues
Issues that should not be re-triaged:
- #1701, #1982, #1435, #1723, #2071 (from prior drip queue)
