# Triage Graph: GraphiteEditor/Graphite

## Investigated

### fix/crash-hiding-zero-input-nodes (ready)
- **Issue**: #3629 -- hiding a context-only node (zero value inputs) crashes the editor
- **Root cause**: `node.inputs.drain(1..)` panics when `inputs` is empty. Context-only nodes like `PointerPositionNode` have zero value inputs.
- **Fix**: Guard with `is_empty()` check. Empty nodes get a synthetic `TaggedValue::None` input pushed; non-empty nodes get truncated to 1.
- **Tests**: Two regression tests added -- zero-input case and multi-input case.
- **Risk**: Low. The change is in `flatten()` which is well-tested. The fix is additive (new guard clause), not a refactor.
- **File**: `node-graph/graph-craft/src/document.rs`

## Review signals
- Bug fix with regression test -- high merge probability for Graphite.
- Small diff (net +64 lines, mostly tests).
- Crash fix tied to a reported issue.
