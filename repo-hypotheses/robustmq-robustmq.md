# Triage Graph: robustmq/robustmq

Stars: 1578 | Language: Rust | Last pushed: 2026-05-12

## AI Policy
None stated. No CONTRIBUTING.md.

## Contributing Policy
No formal policy. CLA required (CLA.md present).

## Issues Triaged

### #1694 - Memory Leak in Retain Message Cache [TRIAGED]
- **Type**: bug_fix (memory leak)
- **Status**: Branch `fix-retain-message-expiry-cleanup` pushed to fork
- **Mechanism**: In `try_send_retain_message`, expired messages were detected but only skipped (continue). Added cleanup: delete from storage via RetainStorage::delete_retain_message + record_mqtt_retained_dec(). Follows same pattern as save_retain_message cleanup (line 60-65).
- **Tests**: No new tests (integration tests require running MQTT broker). Fix follows established storage+metrics pattern.
- **Risk**: Low. 16-line change. delete_retain_message errors are logged and swallowed (warn level), so cleanup failures don't break the send loop.
- **Previous attempt**: gate_fail due to test compilation error (wrong Properties API). This version skips the broken test approach.
- **Competing PRs**: None

## Issues Evaluated but Not Selected

### #1627 - High CPU on linux arm64
- Hard to reproduce, likely architecture-specific.

### #1535 - General memory leak
- Too broad, needs profiling.

### #1796 - DataFusion integration (feat)
- Feature, not a bug fix.

### #1733 - ReasonCode audit (refactor)
- Large refactoring task with subtasks.
