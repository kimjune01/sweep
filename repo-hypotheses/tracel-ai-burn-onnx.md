# Triage Graph: tracel-ai/burn-onnx

72 stars, Rust ONNX-to-Burn codegen. Active maintainer: antimora. Recent merge velocity: ~3 PRs/week.

**Org status: BLOCKED** -- tracel-ai org has blocked kimjune01. PRs cannot be opened upstream.

## Repo character

- Issues #344-352 filed by antimora as structured scoreboard sub-issues from #314 (656 codegen failures)
- Each issue specifies exact test count, error message, proposed fix, and refs
- PR #399 (merged May 2026) established the runtime-weight pattern: `Static` -> module Param, `Dynamic` -> manual math / function-form codegen
- Codebase convention: validation in onnx-ir as ProcessError, not panics in burn-onnx
- Test expectations in expectations.toml gate CI: wrong status = build failure

## Implemented

### #349 Flatten rank-1 input (14 tests) -- DONE
- Branch: `fix/flatten-rank1` on kimjune01/burn-onnx
- Status: skip-codegen -> skip-compile (codegen fixed, compile blocked by pre-existing Shape/Size patterns in expanded LayerNorm)
- Codex: 1 round, caught axis validation gap + .expect() panic + comment mismatch
- Gemini: gate passed, all 3 targeted questions clean
- Build: verified green (cargo test -p onnx-official-tests --no-run)
- Commits: 5 (relax guard, add axis validation, codegen tests, expectations fix, TODO cleanup)
- **BLOCKED**: org-blocked, cannot open PR

## Scored issues (by actionability)

### Tier 1: Mechanical, pattern-established, high test count

| Issue | Tests | Difficulty | Pattern | Notes |
|-------|-------|-----------|---------|-------|
| #341 Pad runtime pads | 41 | Medium | New codegen branch for PadInput::Runtime | Biggest test unlock. Needs runtime tensor read + scatter to full-rank array |
| #352 LayerNorm runtime weight | 19 | Medium | Same as #399 (runtime weight) | Direct application of merged #399 pattern |
| #346 Conv2d/ConvTranspose2d runtime weight | 12 | Medium | Same as #399 | functional conv2d call, same as DeformConv in #399 |
| #349 Flatten rank-1 | 14 | Easy | Relax validation | DONE |

### Tier 2: Moderate complexity, clear fix direction

| Issue | Tests | Difficulty | Pattern | Notes |
|-------|-------|-----------|---------|-------|
| #350 Misc small buckets | 12 | Easy-Medium | 6 independent fixes | max/pow/Selu/Pad-axes/Loop-rank-0/Squeeze -- can cherry-pick |
| #348 Resize custom axes | 8 | Medium | Same as Pad axes expansion | Expand per-axis scales/sizes to full-rank at IR time |
| #345 Split runtime sizes | 8 | Medium | Runtime tensor read | Read split-sizes tensor at forward time |
| #344 Split Shape input | 8 | Easy | Accept ArgType::Shape in match | Route Shape through static-splits path |

### Tier 3: Structural, needs architecture decision

| Issue | Tests | Difficulty | Pattern | Notes |
|-------|-------|-----------|---------|-------|
| #351 AffineGrid/Squeeze | 4+29 | Hard | Deferred rank inference or first-class op | Shape propagation through subgraph branches |
| #371 Kokoro TTS | 1 | Hard | Algorithm-level | atan2 + FFT divergence, residual audio drift |
| #328 Follow-up hardening | N/A | Medium | Code quality | Silent clamping observability, panic->ProcessError, build_node Result type |

### Not actionable (feature requests, long-term)

| Issue | Notes |
|-------|-------|
| #303 ImageScaler | New operator |
| #218 TopK extended | Feature expansion |
| #164 NonMaxSuppression | New operator (PR #294 exists from jcwal1516) |
| #163 Multinomial | New operator |
| #162 ONNX-ML operators | Large scope |
| #160 Quantization operators | Large scope |
| #159 GlobalLpPool | New operator |
| #157 Compress | New operator |
| #156 GlobalMaxPool | New operator |
| #124 Scatter | New operator |
| #22 Export to ONNX | Architecture |
| #23 Custom function | Architecture |
| #24 Function import | Architecture |
| #17 Async codegen | Refactor |

## Dependency graph

```
#314 (scoreboard parent)
  |
  +-- #349 Flatten rank-1 [DONE, blocked]
  |     |
  |     +-- 14 expanded LayerNorm tests: skip-codegen -> skip-compile
  |         (next blocker: Shape/Size codegen patterns)
  |
  +-- #352 LayerNorm runtime weight [follows #399 pattern]
  |     |
  |     +-- 19 non-expanded LayerNorm tests
  |
  +-- #346 Conv2d runtime weight [follows #399 pattern]
  |     |
  |     +-- 12 tests
  |
  +-- #341 Pad runtime pads [largest unlock]
  |     |
  |     +-- 41 tests (attention expanded models)
  |
  +-- #344 Split Shape [easy]
  |     +-- 8 rotary embedding tests
  |
  +-- #345 Split runtime [medium]
  |     +-- 8 tests
  |
  +-- #348 Resize axes [medium]
  |     +-- 8 tests
  |
  +-- #350 Misc [6 independent fixes]
        +-- 12 tests
```

## Review culture

- antimora is primary reviewer, merges within 1-3 days for clean PRs
- Bot (bot-ember) bumps burn dependency weekly
- Established patterns are strongly preferred (see #399 as template)
- Test expectations discipline: every status change must be buildable
- Bug fixes merge readily; feature PRs from external contributors rare but #386 (BenFradet) merged
