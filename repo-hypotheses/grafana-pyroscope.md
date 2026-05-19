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

## Round 2 — review response (2026-05-17)

PR #5139 came back as CHANGES_REQUESTED with two inline comments:

### Comment A (cursor[bot], `pkg/clientpool/ingester_client_pool.go:84`, severity: high)
> HTTP Connect client ignores TLS due to plaintext transport. When
> TLSEnabled is true, the URL scheme changes to https:// but the HTTP
> client from `util.InstrumentedDefaultHTTPClient` uses a hardcoded
> plaintext transport. The underlying `defaultTransport` in
> `pkg/util/http.go` is an `http2.Transport` whose `DialTLSContext`
> always calls `net.Dial` (plaintext), completely ignoring the
> `*tls.Config` parameter.

**Confirmed.** Read `pkg/util/http.go:42-49`:
```go
var defaultTransport http.RoundTripper = &http2.Transport{
    AllowHTTP: true,
    ...
    DialTLSContext: func(ctx, network, addr, cfg *tls.Config) (net.Conn, error) {
        return net.Dial(network, addr)   // ← plaintext, ignores cfg
    },
}
```
This default transport exists to support h2c (HTTP/2 cleartext). With
the original PR's `https://` scheme, the Connect client tries to dial
TLS but `DialTLSContext` returns a plaintext socket — the connection
either fails handshake or succeeds without encryption depending on
server. **High-severity addressable bug.**

### Comment B (simonswine, `PoolConfig` definition, line 29)
> This only works if the ingester's server certificate is signed by a
> CA in the OS trust store. Most Kubernetes deployments use private CAs
> (cert-manager, etc.). No way to specify custom CA, mTLS, or
> skip-verify. Recommend replacing the bool with
> `dskittls.ClientConfig` from `github.com/grafana/dskit/crypto/tls`.

**Confirmed.** Verified dskit/crypto/tls.ClientConfig provides exactly
the missing fields (CAPath, CertPath/KeyPath, ServerName,
InsecureSkipVerify, CipherSuites, MinVersion) plus
`GetTLSConfig() (*tls.Config, error)` and `GetGRPCDialOptions(enabled
bool) ([]grpc.DialOption, error)` — both needed for the fix.

### Fix decision (one diff addresses both)

Kept `TLSEnabled bool` as the explicit switch; added
`GRPCClientTLS dskittls.ClientConfig` as a sibling for the
CA/cert/verify details. (Strict reading of simonswine's "replace the
bool" would drop it; deviating with explanation since `GetTLSConfig`
with zero fields returns a valid system-trust-store *tls.Config and
operators want an explicit on/off — matches dskit's own
`grpcclient.Config.TLSEnabled` + `TLS` sibling pattern. Easy one-line
follow-up if they push back.)

For the gRPC dial: use `cfg.GRPCClientTLS.GetGRPCDialOptions(TLSEnabled)`
— dskit picks insecure when enabled=false, TLS-credentialed when true.

For the HTTP transport: built `newTLSHTTP2Client(tlsConfig)` that
constructs an `http2.Transport` with `TLSClientConfig: tlsConfig` and
NO `AllowHTTP`, NO custom `DialTLSContext`. This is what addresses
Comment A. The default `util.InstrumentedDefaultHTTPClient` path
remains for the plaintext branch (unchanged behavior).

### Tests added

`pkg/clientpool/ingester_client_pool_test.go` (new file, 3 cases):
1. `TLSDisabled_UsesPlaintext` — regression guard for the default path.
2. `TLSEnabled_PropagatesConfigErrors` — invalid CAPath surfaces an
   error from FromInstance rather than silently falling back. Would
   FAIL on master (master never reads CAPath).
3. `TLSEnabled_SystemTrustStoreOK` — TLS with no explicit CA paths
   succeeds (the kept-the-bool path defended in the decision above).

All three pass locally; build + vet + gofmt clean.

### Out of scope, noted

- Same TLS-config-ignored pattern likely exists in
  `pkg/clientpool/store_gateway_client_pool.go`. Original PR scoped
  to ingester per issue #4585; not extending now.
- Long-term: `pkg/util/http.go`'s `defaultTransport` with hardcoded
  plaintext-via-DialTLSContext is a footgun for any other caller that
  ends up with an https:// URL. Worth a separate issue to either
  rename it (clearly h2c-only) or add a TLS-aware variant. Not for
  this PR.

### Frontier edges (open)

- E1: simonswine may push back on keeping the bool. If so, drop
  TLSEnabled and define "enabled" as any-TLS-field-set. One-line change.
- E2: store-gateway pool has the same shape; follow-up PR after this
  one merges (avoids reviewer split-attention).

---

## Reinvestigation: PR #5139 — CI failure (2026-05-19)

**Trigger**: PR went CHANGES_REQUESTED + 5 failing checks on head `93de26e22f72`.

### H_R1: New CLI flags broke the golden help fixture and config reference docs

- **Hypothesis**: Adding `tls_enabled` to `PoolConfig` registers two new CLI flags (`-distributor.tls-enabled`, `-querier.tls-enabled`) that are not present in `cmd/pyroscope/help.txt.tmpl`, `help-all.txt.tmpl`, or `docs/sources/configure-server/reference-configuration-parameters/index.md`. These files are golden fixtures regenerated by `make generate`.
- **Perturbation**: Read the failing logs.
  - `cmd/pyroscope TestHelp/basic` and `TestHelp/all`: testify diff shows exactly two extra lines in actual vs expected — the two new flags (mode: induction).
  - `check-generated`: job output ends with `diff --git a/docs/sources/.../index.md` showing two new `tls_enabled` stanzas under `distributor:` and `querier:` blocks, then `>> There are unstaged changes in the working tree` (mode: induction).
- **Trajectory**: Divergent — single root cause explains all 5 failing checks (4 test matrix entries share the same `TestHelp` golden, plus the doc-regen diff).
- **Kill condition**: Would be killed if the diff contained anything other than the two TLS flags. It didn't.
- **Edge**: regenerate the three golden files and re-push. Commit `a4a0e8a` already did this on the head branch (touched exactly those 3 files, 16 insertions, 0 deletions; head ref on fork advanced from `93de26e` → `a4a0e8a`).

### H_R2: Maintainer-approval gate blocks new CI runs

- **Hypothesis**: a4a0e8a is pushed to the fork, upstream commit-status API reports `success` for the SHA, but `gh run list --branch fix-tls-distributor-ingester` shows zero new workflow runs after the push.
- **Perturbation**: query `gh run list` and PR rollup. Only `license/cla` reports against the new SHA; the 32 workflow checks from the previous SHA have not re-triggered.
- **Trajectory**: Convergent — pyroscope's CI policy requires maintainer approval to run workflows on PRs from external contributors. Until a maintainer clicks "approve and run", the regen commit's effect on CI is invisible.
- **Edge**: not actionable from our side. No code change needed; reviewer attention is the gating resource.

## State

| node   | status     | shape       |
|--------|------------|-------------|
| H_R1   | confirmed  | divergent   |
| H_R2   | confirmed  | convergent  |

## Conclusion

CI breakage on PR #5139 was the golden-fixture/docs-regen miss that always follows adding a registered CLI flag. The regen commit `a4a0e8a` was already pushed before this reinvestigation began and matches the failure surface exactly (2 flags × 3 files). No further commit needed; PR is waiting on maintainer-approved CI run, then re-review of the original TLS fix.

