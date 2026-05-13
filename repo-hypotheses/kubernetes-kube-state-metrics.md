# Triage Graph: kubernetes/kube-state-metrics

**Session**: 2026-05-09
**Agent**: sweep triage agent

## Issue Selection

### Candidates Evaluated

1. **#2898** - CronJob timezone panic ❌ Superseded by competing PR #2907
2. **#2942** - CVE grpc-go release ❌ Dependency update, not a code bug
3. **#2879** - StateSet metrics protocol violation ❌ Competing PR #2884
4. **#2482** - CRD error spam ❌ Competing PR #2884
5. **#2612** - kube_pod_status_reason is 0 ❌ Multiple merged PRs already addressed
6. **#2681** - CSINODES not being scraped ✅ Selected

### Selection Rationale

Issue #2681 has:
- Clear reproduction case (user provided full config)
- Maintainer acceptance (triaged)
- No competing PRs
- Root cause identifiable from logs and config
- Built-in resource (CSINode) being used as custom resource state metric

## Root Cause Analysis

### Discovery

The customResourceState feature uses a CRD discovery mechanism that:
1. Watches CustomResourceDefinition objects via informer
2. Caches GVK→GVKP mappings for discovered CRDs
3. Resolves configured resources against this cache

### The Bug

In `pkg/customresourcestate/config.go:186-202`, when `ResolveGVKToGVKPs` returns an empty slice (resource not in CRD cache), the loop never executes and the resource is silently dropped.

CSINode is a built-in `storage.k8s.io/v1` resource, not a CRD. The discovery mechanism only watches CRDs, so it never finds CSINode.

### Evidence Chain

1. User logs show CSINode NOT in "Active resources" despite being configured
2. Discovery code (`internal/discovery/discovery.go:44-48`) only watches CRDs
3. `ResolveGVKToGVKPs` returns empty slice for non-CRD resources (line 132-146)
4. Config processing loop (line 195) never adds resource to `resolvedGVKPs`

## Fix Implementation

### Code Change

File: `pkg/customresourcestate/config.go`

Added fallback logic after `ResolveGVKToGVKPs` call:
```go
if len(resolvedSet) == 0 {
    // Resource not found in CRD discovery cache. This can happen for built-in Kubernetes resources
    // (e.g., CSINode) that are not CustomResourceDefinitions. Use the resource config as-is.
    klog.InfoS("Resource not found in CRD cache, using as built-in resource", "gvk", resource.GroupVersionKind)
    resolvedGVKPs = append(resolvedGVKPs, resource)
    continue
}
```

### Test Coverage

Added `TestFromConfig_BuiltInResource` to verify:
- Empty CRD cache (no CRDs registered)
- CSINode resource configured with full GVK
- Factory successfully created
- Resource name matches configured plural

### Test Results

```
=== RUN   TestFromConfig_BuiltInResource
I0509 15:28:17.221791   72444 config.go:198] "Resource not found in CRD cache, using as built-in resource" gvk="storage.k8s.io_v1_CSINode"
I0509 15:28:17.221858   72444 config.go:85] "Using custom resource plural" resource="storage.k8s.io_v1_CSINode" plural="csinodes"
--- PASS: TestFromConfig_BuiltInResource (0.00s)
PASS
```

All existing tests continue to pass.

## Artifact Checklist

- [x] Branch created: `fix-csinode-custom-resource-2681`
- [x] Fix implemented
- [x] Test added
- [x] All tests passing
- [x] Commit created
- [x] Drip queue entry written
- [x] TRIAGE_GRAPH.md written

## Next Steps

1. Push branch to fork
2. Drip will create PR when queue slot available
3. PR targets issue #2681

## Notes

This fix enables any built-in Kubernetes resource to be used with customResourceState, not just CSINode. Examples: CSIDriver, StorageClass (when wanting metrics beyond built-in store), etc.

The fix is minimal and safe:
- Only triggers when discovery returns empty (existing behavior is already broken for this case)
- Preserves all existing discovery behavior for actual CRDs
- Uses resource config as-is (same structure that works for CRDs)
