# Triage Graph: k0sproject/k0s

**Date**: 2026-05-09
**Hypothesis**: H1 -- Go, Kubernetes distribution, autopilot subsystem bug
**Status**: READY -- Fix committed on branch `fix/autopilot-status-socket-path`

## Issue Analysis

### #6750: Autopilot ignores --status-socket / custom --run-dir (FIXED)

- **Type**: Bug, configuration ignored
- **Severity**: High -- breaks custom socket path deployments
- **Competing PRs**: None
- **Fix complexity**: Medium -- 11 files, plumbing change

**Root cause**: Autopilot controllers hardcoded `status.DefaultSocketPath` in:
1. `signal/k0s/init.go` -- k0s version handler
2. `signal/k0s/restart_unix.go` -- restart reconciler (version check + PID lookup)
3. `signal/k0s/restarted_unix.go` -- restarted reconciler (version check)
4. `updates/updater.go` -- cron updater (GetStatusInfo call)

When `--status-socket` or `--run-dir` is set, k0s creates the status socket at a non-default path, but autopilot still looks at `/run/k0s/status.sock` and fails to connect.

**Solution**: Added `StatusSocketPath` to `RootConfig`. Both `rootController` and `rootWorker` constructors fall back to `DefaultSocketPath` when empty. Path is threaded through `signal.RegisterControllers` -> `k0s.RegisterControllers` -> restart/restarted structs, and through `updates.RegisterControllers` -> `newUpdater` -> `newCronUpdater`.

**Diff**: 60 insertions, 44 deletions across 11 files
**Testing**: Codex and Gemini both approved. No behavioral change for default path users.

## PR Viability: HIGH

**For**: Clear bug with exact root cause. k0s maintainers (twz123, jnummelin) actively merge fixes. Autopilot subsystem gets less external attention = less competition. The fix is purely mechanical plumbing with safe fallback.
**Against**: 11-file diff is larger than typical first contribution. No tests added (would require integration test with custom socket path).
