# Triage Graph: hyperium/hyper

Generated: 2026-05-09

## Repo Profile

- **Stars:** 15K+
- **Language:** Rust
- **Domain:** HTTP library (HTTP/1 and HTTP/2)
- **Maintainers:** seanmonstar (lead/creator), programatik29
- **Review culture:** Conservative. High bar for API additions. Doc improvements welcomed. Feature additions need strong justification and issue references. seanmonstar reviews everything personally.

## Issue Scan

### Investigated

| Issue | Title | Labels | Verdict | Notes |
|-------|-------|--------|---------|-------|
| #2599 | Expose h2 reset_stream_duration | Feature | **SELECTED** | Long-standing request (2021). Partial implementation -- client side only. Low-risk API surface addition. |
| (none) | Error query methods lack doc comments | Docs | **SELECTED** | All `is_*` methods on `Error` have one-line summaries but no explanatory doc comments. Pure documentation improvement. |

### Competing PR Density

- Very few open PRs (~10)
- Most are long-running feature branches from seanmonstar
- Low external contribution rate -- high merge bar

## Selected: docs/error-kinds + feat/h2-reset-stream-duration

### Hypothesis (docs)

**H0:** The `Error` type's `is_*` query methods have minimal documentation, making it difficult for users to understand what conditions trigger each error variant without reading source code.

### Fix (docs)

- Added detailed doc comments to 9 `is_*` methods
- Each explains what triggers the error and links to relevant builder methods
- Cross-references configuration knobs (max_buf_size, header_read_timeout)

### Hypothesis (h2 reset stream duration)

**H0:** The h2 crate exposes `reset_stream_duration` for tuning how long reset stream state is kept in memory, but hyper doesn't surface this option to users.

### Evidence

- Issue #2599 from 2021 requests this
- h2 builder already has the method
- Memory usage concern in high-throughput connections that reset many streams

### Fix (h2 reset stream duration)

- Added `reset_stream_duration` method to `http2::Builder`
- Forwards to h2's client builder
- Follows pattern of other h2 option forwarding in hyper

### Branches

1. `docs/error-kinds` on `kimjune01/hyper` (1 commit, drip priority 1 -- docs merge easier)
2. `feat/h2-reset-stream-duration` on `kimjune01/hyper` (1 commit, drip priority 2)

## Next Steps

1. Push docs PR first (lowest friction, establishes contributor presence)
2. h2 reset stream duration second (feature, needs seanmonstar approval)
3. If docs merge: consider more documentation improvements before features
