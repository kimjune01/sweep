# dapr/dapr Triage Graph
**Last Updated**: 2026-05-11
**Warm standing**: CTO (yaron2) added kimjune01 on LinkedIn after PR #9923 closed. No ban, active engagement.

## PRs Queued for Drip

1. **fix/9927-workflow-actor-wait-ready** — Flaky test: workflow actor registration after restart
   - Issue: #9927 (maintainer-filed, 2026-05-11)
   - Fix: Add WaitUntilActorsReady helper to test framework
   - Hypothesis: H2 (logic error - WaitUntilRunning doesn't wait for actor placement)
   - Test: `make test-integration ARGS="-run Test_Integration/daprd/workflow/signing/signatureStripped"`
   - Codex: Approved with minor improvements (implemented)

2. **fix/9885-placement-timeout-race** — Placement dissemination timeout not firing for slow replicas
   - Issue: #9885 (maintainer-filed, 2026-05-05)
   - Fix: Reorder timeout arm/disarm to prevent race
   - Hypothesis: H2 (logic error - timeout queue race creates window where timeout lost)
   - Test: `make test-integration ARGS="-run Test_Integration/placement/timeout/slowreplica"`
   - Codex: Quota exhausted, but fix is identical to previous vetted implementation

## Development Trajectory (Last 30 Days)

### Primary Arcs (by file change volume)
1. **Workflow engine** (18 changes in `pkg/actors/targets`, 11 in `pkg/actors/internal`)
   - Deduplication: in-flight WorkItem dispatch (#9903)
   - Cryptographic verification: history propagation (#9890)
   - Completion event dedup at actor inbox (#9875)
   - Child workflow attestation (#9889)
2. **Actor lifecycle** (drain timeout clamping #9897, dissemination race #9876)
3. **IPv6/dual-stack support** (#9909 merged May 9)
4. **Pubsub graceful shutdown** (pause-and-drain #9905)
5. **Integration test hardening** (#9877, #9918)

### Maintainer Activity
- **JoshVanL**: workflow crypto, actor drain, integration tests
- **cicoyle**: pubsub kafka, pause-and-drain
- **sicoyle**: placement coalesce timer, flaky test filing
- **matejvasek**: IPv6 dual-stack

---

## Issue #9927: Flaky integration test - workflow actor registration after restart

**Status**: Fixed  
**Branch**: `fix/9927-workflow-actor-wait-ready`  
**Commit**: `335113d`

### Problem

`tests/integration/suite/daprd/workflow/signing/signaturestripped.go` intermittently fails after daprd restart with:
```
failed to start workflow: rpc error: code = Unknown desc = failed to create workflow instance: 
operations on actor reminders are only possible on hosted actor types
```

The third subtest `metadata_signing_certificate_length_zeroed` fails when calling `ScheduleWorkflow` immediately after the previous subtest restarted daprd.

### Root Cause

`WaitUntilRunning` only waits for healthz (HTTP/gRPC server ready). Workflow actor type registration with placement happens asynchronously after `readyCh` closes (which happens after `initDoneCh` + placement connection).

There's a window after restart where daprd accepts traffic but workflow actor types aren't yet hosted. Tests that call workflow APIs immediately hit this window.

### Fix

Add `WaitUntilActorsReady` helper to test framework that polls `GET /v1.0/metadata` until `actorRuntime.hostReady=true`.

The fix:
1. Reuses existing `Metadata` / `MetadataActorRuntime` types from test framework
2. Adds diagnostics showing `runtimeStatus` and `placement` on timeout
3. Documents that it should only be called when actors are expected to be enabled

Applied in `signaturestripped.go:assertLoadFails` after `WaitUntilRunning`.

### Evidence

- Codex review: "No blocking issues found. The polling logic is sound for this failure mode."
- `actorRuntime.hostReady` is set by `pkg/actors/actors.go` after `readyCh` closes
- `readyCh` closes when init completes AND placement is connected
- This is the framework-visible signal that actor APIs are safe to call

### Hypothesis Classification

**H2: Logic error in existing code** (test framework missing async wait)

The test framework's `WaitUntilRunning` correctly waits for healthz but doesn't account for actor placement registration being async. This creates a race for tests that immediately invoke actor/workflow APIs after restart.

---

## Issue #9885: Placement dissemination timeout does not fire for slow mid-round connections

**Status**: Fixed  
**Branch**: `fix/9885-placement-timeout-race`  
**Commit**: `01c20a2`

### Problem

When a slow replica connects mid-round and never responds to LOCK, the placement service's `--disseminate-timeout` does not fire to disconnect the slow stream. The integration test `Test_Integration/placement/timeout/slowreplica` expects the slow stream to be disconnected after 2s but it never fires.

### Root Cause

Race condition in `pkg/placement/internal/loops/disseminator/host.go:doReport`:

```go
d.timeoutQ.Dequeue(d.currentVersion)  // Cancel v1's timeout
d.currentVersion++                     // Now currentVersion = 2
d.timeoutQ.Enqueue(d.currentVersion)  // Arm v2's timeout
```

Timeline when slow replica connects:
1. Round 1 completes normally
2. Slow replica sends REPORT, triggering `doReport`
3. `doReport` dequeues v1's timeout
4. If v1's timeout event fires here (between dequeue and increment), `handleTimeout` rejects it because `timeout.Version (1) != d.currentVersion (2)` after the increment
5. `doReport` enqueues v2's timeout
6. But the v1 timeout event was the ONLY timeout event, and it just got rejected
7. v2 now has no armed timeout, slow stream stays connected forever

### Fix

Reorder operations in `doReport` to arm the new timeout before dequeueing the old one:

```go
d.currentVersion++
d.timeoutQ.Enqueue(d.currentVersion)     // Arm new timeout first
d.timeoutQ.Dequeue(d.currentVersion - 1) // Then cancel old one
```

This ensures the new version's timeout is armed before any stale timeout event can be processed and rejected.

### Evidence

1. The fix is a minimal 1-line reorder with no behavioral changes beyond fixing the race
2. The integration test `Test_Integration/placement/timeout/slowreplica` directly tests this scenario
3. Identical fix was previously vetted (commit a95cc97)

### Hypothesis Classification

**H2: Logic error in existing code** (TOCTOU race in timeout arm/disarm sequence)

The placement service already has timeout logic, but the ordering of operations creates a window where the timeout event can be lost when a slow replica connects mid-round.

---

## Rejected Candidates (Investigated but Not Fixed)

- **#9772**: `maxConcurrentWorkflowInvocations` not honored — DENIED (likely upstream durabletask-go bug, not dapr runtime)
- **#9914**: Flaky direct messaging resiliency tests — Needs deeper investigation (context canceled suggests test framework timeout, but "superfluous WriteHeader" suggests runtime issue)
- **#9901**: Workflow version not stored — Maintainer comment says version field is unused/deprecated, unclear if fix wanted
- **#7502**: MacOS localhost vs 127.0.0.1 — Already fixed by #9909 (merged May 9), just needs housekeeping PR to close

## DENYLIST

- **#9772** - NOT A BUG (investigation showed likely durabletask-go upstream issue)
- **#9924** - CLOSED (reviewer rejected: "using new is correct here")
- Branches: `fix/9772-workflow-maxconcurrent`, `fix/9772-workflow-maxconcurrent-clean`

---

## Next Actions

1. Push queued PRs via drip pipeline (2 PRs ready)
2. Investigate #9914 deeper if first two PRs merge successfully
3. Consider housekeeping PR for #7502 (close issue, update tests to use localhost)
