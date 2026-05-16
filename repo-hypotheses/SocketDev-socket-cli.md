# Triage Graph: SocketDev/socket-cli

## Session: 2026-05-11

### Repo Context
- **Maintainers**: jdalton (collaborator), simonhj, mtorp
- **Stack**: TypeScript (ESM), Node >= 26, pnpm monorepo, vitest
- **Architecture**: CLI delegates to sfw (Socket Firewall) for npm/pnpm/yarn wrapping
- **Key insight**: Most open issues (#1160, #1036-main, #946) are in sfw package, not this CLI

### Denylist
- **#971** — already fixed (dripped), namespace in shallow output
- **#760** — already fixed upstream (commit 35d4d84cb), backwards semver removed
- **#1058** — server-side 500 error, not fixable in CLI
- **#1126** — server-side URL detection false positive
- **#1123** — Cloudflare infrastructure issue
- **#947** — server-side rate limiting
- **#68** — large feature request, not first-contribution material

### Investigated

#### #1036 — NODE_OPTIONS override (CLI-side instance)
- **Status**: TRIAGED
- **Branch**: fix/optimize-preserve-node-options
- **Finding**: The reported issue is in sfw (socket npm), but agent-installer.mts in the optimize command has the identical bug pattern. `NODE_OPTIONS` is set to Socket's hardening flags only, silently dropping user-configured options like `--max-old-space-size`.
- **Fix**: Prepend `process.env['NODE_OPTIONS']` before Socket flags with `filter(Boolean).join(' ')`.
- **Commits**: 2 (NODE_OPTIONS fix + filterFlags --no-<name> fix)

#### filterFlags --no-<name> leak (discovered during investigation)
- **Status**: TRIAGED (same branch)
- **Finding**: `filterFlags` only special-cased `--no-banner` and `--no-spinner`. The `animateHeader` flag (also `default: true`) had `--no-animate-header` leaking through to forwarded npm/pnpm/yarn processes.
- **Fix**: Add both `--<name>` and `--no-<name>` to filter set for all boolean flags.

#### #1160 — Node v24 crash (ERR_MISSING_OPTION)
- **Status**: KILLED (sfw-side)
- **Reason**: Bug is in `shadow-npm-bin2.js` which wraps `--node-options` with single quotes in a `spawn()` call. This file is in the sfw package, not socket-cli.

#### #946 — mise npm detection
- **Status**: KILLED (sfw-side)
- **Reason**: sfw tries to `require()` the npm binary, which under mise is a bash wrapper script. The CLI's path-resolve.mts already handles mise directory layout (lines 67-70) but sfw's execution model is the problem.

#### #999 — README/FAQ inconsistency
- **Status**: KILLED (docs/marketing)
- **Reason**: Issue is about npm-published README vs docs.socket.dev FAQ. Not a code bug.

### Evidence
- Node >= 26 required for tests. Local machine has v22. Tests verified by code inspection only.
- The sfw package handles all npm/pnpm/yarn wrapping; socket-cli just locates binaries and hands off.
- jdalton is the primary reviewer; simonhj and mtorp contribute features and fixes.
