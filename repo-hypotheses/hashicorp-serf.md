# Triage Graph: hashicorp/serf

## Issue #500: force-leave is not validating input

**Status**: Fixed  
**Branch**: fix/500-force-leave-validation  
**Commit**: 00c837e6b95075f139871e207a04c199ee1449eb  

### Problem

The `serf force-leave` command accepts any node name without validation. If users provide a nonexistent node name (due to typo or confusion between IP and node name), the command silently succeeds with exit code 0, giving no indication that the operation did nothing.

This mirrors the same bug reported in Consul (#3757), where the force-leave command also lacked input validation.

### Solution

Added validation to check if the specified node exists in the cluster before attempting force-leave:

1. Query `client.Members()` to get the current cluster member list
2. Search for the specified node name in the member list
3. Return an error if the node is not found
4. Only proceed with force-leave if the node exists

### Changes

**Modified files**:
- `cmd/serf/command/force_leave.go`: Added member existence check before ForceLeave/ForceLeavePrune
- `cmd/serf/command/force_leave_test.go`: Added test case for nonexistent node validation

### Evidence

The fix is minimal and directly addresses the issue. The validation happens at the CLI layer, before making the RPC call to the agent. This provides immediate feedback to the user without requiring any changes to the serf core or RPC layer.

Error message format: `Node 'nonexistent-node' not found in cluster`

### Test Coverage

Added `TestForceLeaveCommandRun_nonexistentNode` to verify:
- Command returns exit code 1 for nonexistent nodes
- Error message contains "not found"

Existing tests verify:
- Normal force-leave still works for valid nodes
- Prune flag works correctly
- Missing node name argument is caught
