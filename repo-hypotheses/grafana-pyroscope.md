# Triage Graph: grafana/pyroscope

**Date**: 2026-05-09
**Hypothesis**: H2/H3 — Grafana ecosystem, Go, good-first-issues, continuous profiling tool
**Status**: ACTIONABLE — Bug fix committed on branch `fix-tls-distributor-ingester`

## Issue Analysis

Scanned 9 good-first-issue and 20 bug issues. Most actionable:

### #4585: Distributor TLS Bug (FIXED)
- **Type**: Bug, TLS configuration ignored
- **Severity**: High — breaks TLS deployments
- **Reproduction**: Clear, single-node TLS setup
- **Competing PRs**: None
- **Maintainer signal**: Issue links to exact code line in repo
- **Fix complexity**: Low — add TLS flag to pool config

**Root cause**: `pkg/clientpool/ingester_client_pool.go` hardcoded:
1. `"http://"` scheme for Connect-RPC client (line 65)
2. `insecure.NewCredentials()` for gRPC health client (line 58)

**Solution**: Added `tls_enabled` flag to `PoolConfig`. When enabled:
- Uses `https://` scheme for HTTP/2 Connect client
- Uses `credentials.NewTLS(&tls.Config{})` for gRPC

**Diff**: 25 insertions, 6 deletions
**Testing**: Builds successfully, no existing tests in pkg/clientpool

### Other Issues (Not Pursued)

**#3646: NodeJS Docker Example Broken**
- Still broken in v0.4.3 despite attempted fix
- Requires NodeJS/npm ecosystem knowledge
- Lower priority than TLS security bug

**#3616: Malformed Flame Graph (Delta Heap)**
- Negative value sanitization
- Had competing PRs #3626, #3627 (both closed)
- Complex: affects pprof compatibility
- Deferred

## Pipeline Learnings

1. **Grafana ecosystem pattern**: Same TLS bug likely exists in `store_gateway_client_pool.go` — but querier call site would need update. Focused on distributor (issue #4585) for minimal fix.

2. **Bug over feature**: Pyroscope maintainers close feature PRs but need bug fixes. TLS is a deployment blocker.

3. **Code pointers in issues**: Issue #4585 linked exact line number — high-quality signal.

## Outcome

Branch `fix-tls-distributor-ingester` ready for drip queue.
Commit: 93de26e22
