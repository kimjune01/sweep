# Triage Graph: hashicorp/serf

## Issue #500: force-leave is not validating input

**Status**: Shipped (PR #807 OPEN, blocked on CLA)
**Branch**: fix/500-force-leave-validation
**PR**: https://github.com/hashicorp/serf/pull/807

### Problem

`serf force-leave <node>` accepts any node name without checking the local member list. A typo or IP/name confusion silently exits 0 with no indication the operation was a no-op. Same shape as Consul #3757.

### Solution (as shipped)

Before broadcasting force-leave, query `client.Members()`:
- If the query fails → emit a warning, still broadcast (degraded-network robustness).
- If the node is not found → emit a warning, still broadcast (idempotent: exit code 0).
- If the node is found → proceed silently.

Force-leave remains idempotent; the change is purely observability.

### Changes

- `cmd/serf/command/force_leave.go`: member lookup + two warning paths before `ForceLeave` / `ForceLeavePrune`.
- `cmd/serf/command/force_leave_test.go`: `TestForceLeaveCommandRun_nonexistentNode` asserts exit 0 + "not found" in output.

### Reframe from prior graph

Earlier draft proposed exit-1 hard error on missing node. Shipped version is exit-0 + warning. Reason: force-leave's documented contract is idempotent; converting a no-op into an error would break callers that rely on retry-safety (config-management loops, cluster teardown scripts). Warning preserves observability without breaking the contract.

### Current frontier

**One open edge: CLA signature.**

- `license/cla` status check is PENDING.
- No maintainer review, no comments other than `hashicorp-cla-app`.
- This is a policy gate, not a technical question. No perturbation surface — investigation halts here. See [[reference_hashicorp_cla_gate]].

### Pruning log

- H1 (exit-1 hard error): killed by idempotency contract — would break retry-safe callers.
- H2 (skip the Members() call when prune flag is set): killed — prune is the more dangerous path, observability matters more there, not less.
- H3 (attest verdict `test_fails_on_fix` indicates a real regression): **killed**. The 2026-05-18T06:47 reinvestigate trigger reported `make: *** [GNUmakefile:39: subnet] Error 1`. Root cause: `make test` depends on the `subnet` target, which runs `scripts/setup_test_subnet.sh`. That script pings `127.0.0.2`, fails on Linux containers (sweep-tester is Linux), then bails with "Can't setup interfaces on non-Mac. Error!" before any Go test runs. The fix code never executes under this `test_cmd`. The Go tests themselves are fine; only the subnet prereq is environment-incompatible with the docker test_env.

### Frontier — test_env mismatch

- The hashicorp/serf project entry has `test_cmd: make test` + `test_env: docker:sweep-tester:latest`. The combination is unrunnable: `make test` requires host-level `sudo ifconfig lo0 alias` on Darwin, which doesn't translate to a Linux container.
- Open edge for the substrate (not for this PR): the project's `test_cmd` should be either `go test ./...` (skipping subnet/vet) with the container pre-configured for 127.0.0.x routing, or scoped to packages that don't need multi-IP loopback (`cmd/serf/command/...` mostly does, so even scoping is fragile).
- Until the env is fixed, attest verdicts on hashicorp/serf PRs are not informative — every PR will report `test_fails_on_fix` for the same env reason. Recommend muting attest on this repo or switching `test_cmd`.

### Halt

CLA gate is unsigned + cannot be signed from this account; attest env-mismatch makes the gate output non-informative. No further code changes warranted. Investigation halts.
