# Triage Graph: apache/opendal

Generated: 2026-05-09

## Repo Profile

- **Stars:** 10K+
- **Language:** Rust
- **Domain:** Data access layer (unified API for storage services)
- **Maintainers:** Xuanwo (lead), ClSlaid, WenyXu
- **Review culture:** Apache project with structured review. PRs need conventional commit messages (feat/fix/chore). Service-specific changes reviewed by service maintainers. Tests expected. Issue references valued.

## Issue Scan

### Investigated

| Issue | Title | Labels | Verdict | Notes |
|-------|-------|--------|---------|-------|
| #4842 | azdls: support user_metadata | Enhancement | **SELECTED** | Maintainer-acknowledged gap. Clear REST API spec for x-ms-properties. No competing PR. |
| #4593 | Buffer: add split_to and split_off | Enhancement | **SELECTED** | Feature request matching bytes::Bytes API convention. Clean O(1) implementation. No competing PR. |

### Competing PR Density

- High PR volume (~50+ open), many from core contributors
- Service-specific PRs don't conflict with each other
- Core API changes reviewed more carefully

## Selected: #4842 (azdls user_metadata) + #4593 (Buffer split)

### Hypothesis (azdls)

**H0:** Azure Data Lake Storage Gen2 service lacks user_metadata support despite the capability existing in the ADLS Gen2 REST API via x-ms-properties header.

### Evidence (azdls)

- Issue #4842 explicitly requests user_metadata for azdls
- x-ms-properties header uses base64-encoded comma-separated key=value pairs
- Other storage services (s3, gcs) already implement user_metadata

### Fix (azdls)

- `encode_properties`/`decode_properties` helpers for x-ms-properties format
- Set header on Path Create, parse from Path Get Properties in stat
- Remove `action=getStatus` from stat URL so user-defined properties are returned
- Enable `write_with_user_metadata` capability
- 7 unit tests for encode/decode

### Hypothesis (Buffer)

**H0:** Buffer lacks split_to/split_off methods that would match the bytes::Bytes API convention for zero-copy buffer splitting.

### Fix (Buffer)

- `split_to(at)`: returns [0, at), self becomes [at, len) -- O(1)
- `split_off(at)`: returns [at, len), self becomes [0, at) -- O(1)
- Both reuse underlying storage via slice/advance/truncate
- Unit tests + fuzz tests for contiguous and non-contiguous buffers

### Branches

1. `feat/azdls-user-metadata` on `kimjune01/opendal` (2 commits, drip priority 1)
2. `feat/buffer-split` on `kimjune01/opendal` (2 commits, drip priority 2)

## Next Steps

1. Push azdls first (service-specific, lower review friction)
2. Buffer split second (core API, higher scrutiny)
3. If both merge: look for other service capability gaps
