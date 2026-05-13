# Triage Graph: aquasecurity/trivy

## Session: 2026-05-09

### Issue #8087: Node-collector timeout on tainted nodes

**Status**: Fixed ✓  
**Branch**: `fix-8087-node-collector-tolerations`  
**Commit**: `17af9c4f167208130525b51ad7f3023fb581fac6`

#### Problem Analysis

The node-collector job times out when scanning Kubernetes clusters with tainted control-plane nodes. The job cannot be scheduled without tolerations, but users must manually specify these via `--tolerations` flag.

Error observed:
```
FATAL Fatal error get k8s artifacts with node info error: running node-collector job: runner received timeout
```

#### Root Cause

The `nodeCollectorOptions()` function in `pkg/k8s/commands/cluster.go` passes user-provided tolerations directly to the node-collector job. When no tolerations are provided, the job pod cannot be scheduled on tainted nodes (common for control-plane nodes with `node-role.kubernetes.io/control-plane:NoSchedule` or legacy `node-role.kubernetes.io/master:NoSchedule` taints).

#### Solution Implemented

Added default tolerations for common control-plane taints when no custom tolerations are specified:

1. **Import corev1**: Added `corev1 "k8s.io/api/core/v1"` import
2. **Default tolerations helper**: Created `getDefaultTolerations()` returning:
   - `node-role.kubernetes.io/control-plane` with `TolerationOpExists` + `NoSchedule`
   - `node-role.kubernetes.io/master` with `TolerationOpExists` + `NoSchedule`
3. **Conditional application**: Modified `nodeCollectorOptions()` to apply defaults only when `len(opts.Tolerations) == 0`
4. **Test coverage**: Added `cluster_test.go` with `TestGetDefaultTolerations()`

#### Files Changed

- `pkg/k8s/commands/cluster.go`: Added default tolerations logic
- `pkg/k8s/commands/cluster_test.go`: New test file

#### Impact

- **Backward compatible**: Custom tolerations still override defaults
- **UX improvement**: No manual toleration configuration needed for standard clusters
- **Scope**: Only affects clusters where no tolerations are explicitly provided

#### Competing PRs

None found via `gh search prs --repo aquasecurity/trivy --state open "8087"`

#### Actionability Score

- **Maintainer acknowledgment**: Issue has 3 comments, desired behavior clearly stated
- **Mechanical acceptance**: Bug fix with clear reproduction steps
- **Simplicity**: 2 files changed, ~50 lines added
- **Impact**: High (affects all users scanning clusters with tainted control-plane nodes)

**Score**: 9/10

#### Next Steps

1. Drip queue entry created at `~/.sweep/drip-queue/aquasecurity-trivy.jsonl`
2. Awaiting push to fork and PR creation
3. Monitor for CI feedback and maintainer review
