# Triage Graph: openbao/openbao (kimjune01)

**Scan date:** 2026-05-09
**Language:** Go
**Default branch:** main

## Scan Table

| # | Title | Type | Score | Signal | Status |
|---|-------|------|-------|--------|--------|
| 2594 | Unix socket filesystem mode is not set if user and/or group are null | bug | 8/10 | good-first-issue, help-wanted, maintainer (cipherboy) confirmed | IN PROGRESS |
| 3053 | Raft Autopilot crashes application | bug | 7/10 | Production panic, nil deref, clear stack trace | TAKEN (PR #3054 by mpldr) |
| 2996 | "error parsing JSON" for large json payloads | bug | 5/10 | UX improvement, unclear acceptance criteria | PENDING |
| 3003 | JSON pointer claim_mappings not enforced as required claims | bug | 5/10 | auth/jwt, 2 comments | PENDING |
| 3002 | OIDC role validation race condition | bug | 6/10 | Race condition, misleading error | PENDING |
| 2823 | KV v2 LIST on empty mount fails with read-only transaction | bug | 6/10 | Clear repro, core/storage | PENDING |
| 3026 | AppRole role-id read with wrapping fails on standby | bug | 4/10 | Complex HA issue, 4 comments, core/horizontal | PENDING |
| 2921 | Crash with inconsistent database (half created namespace) | bug | 4/10 | Complex, namespace-related | PENDING |

## Selected Fix

**#2594** — The guard condition in `command/server/listener_unix.go` uses `&&` requiring all three of socket_mode, socket_user, socket_group to be non-empty. When only socket_mode is specified, the config is nil and permissions are never applied.

**Fix:** Change `&&` to `||`. The downstream `setFilePermissions()` already handles each field independently. Added test `TestUnixListener_SocketModeOnly`.

**Branch:** `fix/unix-socket-mode-without-user-group`

### Competing PRs

| # | Title | State | Outcome |
|---|-------|-------|---------|
| 2701 | fix: apply socket file mode when user/group are not set | closed | Not merged |
| 2919 | fix: allow mode-only socket permissions without requiring user/group | closed | Not merged (AI-generated) |
| 2940 | listenerutil: only chown when socket_user or socket_group is set | closed | Not merged |

Three prior attempts, all closed without merge. The issue remains labeled good-first-issue + help-wanted. Our fix is minimal (one operator change + test) vs prior PRs that over-engineered the solution by restructuring setFilePermissions.

### Risk

Moderate competing-PR density but all prior attempts failed. The fix is a one-character change (`&&` to `||`) with a test, which is the simplest possible approach. The `no AI certification` checkbox in their PR template is a concern -- this PR must be submitted manually with the checkbox honestly filled.

## Repository Profile

- **Star count:** ~4.5k
- **Merge rate for externals:** Unknown (new repo, forked from HashiCorp Vault)
- **Review speed:** Active maintainer (cipherboy) responds within days
- **PR template:** Requires DCO sign-off and explicit "no AI" certification
- **Base branch:** main
