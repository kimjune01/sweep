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

---

## Reinvestigate cycle 2026-05-18

**Trigger:** reinvestigate-from-attest, PR #10643.

**State at fetch (gh pr view):**
- state: OPEN, mergeable: MERGEABLE, reviewDecision: REVIEW_REQUIRED
- statusCheckRollup: license/cla = SUCCESS (single check, green)
- CLA: signed.

**Classification:** convergent — no broken CI to patch. The attest rollup that fired this cycle was stale (context pack itself flagged "CI may have recovered or rollup is stale"). PR is healthy and waiting on human review only.

**Edge:** none. No frontier opens from a green PR. Halt — no patch to ship, no investigation to extend.

**Action:** none. The PR is in the maintainer's court.

## Reinvestigate cycle 2026-05-19

**Trigger:** reinvestigate-from-attest, PR #10643. Re-fire of the 2026-05-18 cycle.

**State (gh pr view):** OPEN, MERGEABLE, REVIEW_REQUIRED; statusCheckRollup = `license/cla` SUCCESS only. No failing checks.

**Classification:** identity — running reinvestigate on a converged green PR produces the same node. No new signal.

**Edge:** none. Halt. Suggests an upstream filter: reinvestigate-from-attest should skip PRs whose only check is `license/cla=SUCCESS` and reviewDecision=REVIEW_REQUIRED (purely human-gated waiting state) so the same node isn't re-emitted on a cadence.

## Reinvestigate cycle 2026-05-19 (2nd fire)

**Trigger:** reinvestigate-from-attest, PR #10643. Third consecutive identity fire — meets the outer-loop fixed-point halt condition ("Three consecutive iterations produce the same diagnosis").

**State (gh pr view):** OPEN, statusCheckRollup = `license/cla=SUCCESS` only, REVIEW_REQUIRED, no failing checks. Identical to prior two cycles.

**Classification:** fixed point. Halt.

**Edge:** none in-repo. The repeated re-fire is itself the signal — the actionable artifact is upstream of this graph: suppress reinvestigate-from-attest when the sole check is `license/cla=SUCCESS` and reviewDecision is REVIEW_REQUIRED. Flagged for retro.
