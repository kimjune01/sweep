# Triage Graph: vectordotdev/vector

**Repository:** vectordotdev/vector  
**Hypothesis:** H1/H4 — Rust observability pipeline, 5 good-first-issues, Datadog-backed, 21.8K stars  
**Date:** 2026-05-09

## Issue Selection

### Candidates Reviewed
- **#25045** (OTLP timestamp bug) — **SELECTED**
  - Created: 2026-03-25
  - Type: Bug fix
  - Labels: type: bug, domain: codecs
  - No competing PRs
  - Clear root cause identified in issue description
  - Affects OTLP trace events when using LogNamespace::Legacy

- #23606 (VRL panic) — Good alternative, has reproducer
- #23660 (Tokio timer panic) — Multiple user reports, no clear fix path
- #23672 (macOS test disabled) — Good first issue, but test-only

### Selection Rationale
Issue #25045 was selected because:
1. Clear bug with known root cause (documented in the issue)
2. No competing PRs
3. Recent issue (March 2026) showing active maintenance
4. Affects core functionality (OTLP traces)
5. Fix is surgical — one-line change with clear reasoning

## Root Cause Analysis

**Problem:** When `use_otlp_decoding.traces = true` and `log_namespace: legacy`, the OtlpDeserializer delegates to ProtobufDeserializer with `LogNamespace::Legacy`, which injects a spurious timestamp into trace events.

**Code Location:** `lib/codecs/src/decoding/format/otlp.rs:186`

**Mechanism:**
1. OtlpDeserializer calls `self.traces_deserializer.parse(bytes, log_namespace)`
2. ProtobufDeserializer in Legacy mode injects timestamp (lines 153-159 of protobuf.rs)
3. The log event is converted to a trace event, but the timestamp persists

**Fix:** Always use `LogNamespace::Vector` when parsing traces, since log_namespace semantics don't apply to trace signal types.

## Implementation

**Branch:** `fix/otlp-trace-timestamp-25045`

**Changes:**
- Modified `lib/codecs/src/decoding/format/otlp.rs`
  - Line 186: Changed from `log_namespace` to `LogNamespace::Vector`
  - Added explanatory comment linking to #25045
  - Added regression test `deserialize_traces_with_legacy_namespace_should_not_inject_timestamp`

**Test Results:**
- New test passes
- All 6 OTLP tests pass
- All 203 codec tests pass

**Commit:** fd9bd09e9

## Evidence

### Issue State
- Open since 2026-03-25
- No comments (maintainer-created)
- No existing PRs
- Clear acceptance criteria: no timestamp injection for traces

### Test Coverage
```rust
#[test]
fn deserialize_traces_with_legacy_namespace_should_not_inject_timestamp() {
    // Test verifies fix for #25045
    let deserializer = OtlpDeserializer::default();
    let trace_bytes = create_traces_request_bytes();
    
    let events = deserializer.parse(trace_bytes, LogNamespace::Legacy).unwrap();
    let trace = events[0].as_trace();
    
    // Verify no spurious timestamp
    if let Some(timestamp_key) = log_schema().timestamp_key_target_path() {
        assert!(trace.get(timestamp_key).is_none());
    }
    
    // Trace data still valid
    assert!(trace.get(RESOURCE_SPANS_JSON_FIELD).is_some());
}
```

### Hypothesis Validation
- **H1 (Active maintenance):** Confirmed — issue created by maintainer in March 2026
- **H4 (Bug fixes merge):** TBD — will test with this PR

## Next Steps
1. Queue for /drip: `~/.sweep/drip-queue/vectordotdev-vector.jsonl`
2. Monitor for CI results
3. Address review feedback if any
4. Track merge time for H4 validation
