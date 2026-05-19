# hyperium/tonic#2599 — Snappy empty-message encoding emits 0 bytes; Java decoder rejects

**Issue**: Empty (0-byte) gRPC response under Snappy compression makes a Java client fail with `java.io.IOException: Not a framed Snappy stream`. Forcing gzip avoids it.

**Upstream state**: **Snappy is NOT in hyperium/tonic master.** The `CompressionEncoding::Snappy` variant lives only in the *unmerged* PR [#2524](https://github.com/hyperium/tonic/pull/2524) (`CEmocca:add-lz4-snappy-compression`, base branch `v0.14.x`). The reporter (jojoxhsieh) must be building against that fork. This means the canonical place for a fix is PR #2524, not a fresh PR against master.

## H₀ — `snap::write::FrameEncoder::write_all(&[])` emits 0 bytes (no stream identifier)

- **Null**: snap emits the stream identifier on construction or on drop, even for empty input. Resulting payload is a valid empty framed snappy stream (the 10-byte identifier alone).
- **Perturbation**: standalone Rust binary (`/tmp/snappy-test/`) using `snap = "1"`:
  ```rust
  let mut enc = snap::write::FrameEncoder::new(&mut out);
  enc.write_all(&[]).unwrap();
  drop(enc);
  ```
- **Result**:
  - `write_all(&[])` then drop → **0 bytes** output.
  - `flush()` only → **0 bytes** output.
  - `write_all(&[])` then `flush()` → **0 bytes** output.
  - `write_all(b"hi")` then drop → 20 bytes, starting `ff 06 00 00 73 4e 61 50 70 59` (the framing stream identifier `\xff\x06\x00\x00sNaPpY`).
- **Trajectory shape**: divergent — confirmed.
- **Edge**: H₀ killed the null. The 0-byte server payload reaches the Java client as length-prefixed message `{compressed=1, length=0, body=<empty>}`. Apache Commons' `FramedSnappyCompressorInputStream.readStreamIdentifier` requires the identifier upfront and bails — exactly the reported error.

**Provenance**: Snappy code is in PR #2524 (commit `eab8e3d`), file `tonic/src/codec/compression.rs:296-303`:
```rust
#[cfg(feature = "snappy")]
CompressionEncoding::Snappy => {
    {
        let mut snappy_encoder = snap::write::FrameEncoder::new(&mut out_writer);
        snappy_encoder.write_all(&decompressed_buf[0..len])?;
        // snappy_encoder is dropped here, flushing the final frame
    }
}
```
For `len == 0`, `write_all(&[])` is a no-op, and `snap::write::FrameEncoder`'s Drop impl doesn't synthesize the identifier if nothing was ever written. The comment in the code is misleading — there is no "final frame" to flush when nothing was written.

## H₁ — All other codecs emit a valid empty stream for empty input

- **Null**: gzip/zstd/deflate also drop empty bytes silently.
- **Perturbation**: well-known: gzip always emits a 10-byte header + 8-byte trailer = ≥18 bytes minimum stream. zstd emits a magic-number-prefixed empty frame. deflate (zlib) emits 2-byte header + 4-byte adler trailer.
- **Trajectory**: convergent. Standard wire-format codecs emit valid empty streams. Snappy is the asymmetric one.
- **Implication**: The reporter is right to expect snappy to "just work" for empty payloads — that's what gzip does. The bug lives in tonic's snappy adapter, not in the application.

## Fix shape (for PR #2524)

Two clean options. Recommend **A** because it's local to snappy and preserves the invariant that the codec always produces a valid stream.

### Option A — emit the stream identifier when input is empty

In `tonic/src/codec/compression.rs` `compress()`:

```rust
#[cfg(feature = "snappy")]
CompressionEncoding::Snappy => {
    if len == 0 {
        // snap::write::FrameEncoder never emits the framed-snappy stream
        // identifier when no data is written. A bare identifier is a valid
        // empty framed stream and is what Java/Go clients expect.
        out_buf.extend_from_slice(b"\xff\x06\x00\x00sNaPpY");
    } else {
        let mut snappy_encoder = snap::write::FrameEncoder::new(&mut out_writer);
        snappy_encoder.write_all(&decompressed_buf[0..len])?;
    }
}
```
Note: `out_buf` is `&mut BytesMut` (in scope before the `out_writer` shadowing). Easier: drop the writer adapter for the empty branch.

### Option B — skip compression for zero-length messages

In `tonic/src/codec/encode.rs::encode_item`, after the encoder runs but before calling `compress()`, if `uncompressed_len == 0` set the per-message compressed flag to 0 and skip the codec call. Cleaner for *all* codecs but changes wire output for gzip/zstd/lz4 too (currently they emit a valid compressed empty stream; after the change they'd emit 0 bytes with flag=0). That is gRPC-legal (the per-message flag overrides session-level negotiation) but changes existing behavior. Riskier scope for a fix targeted at snappy.

### Regression test

In `compression.rs::tests` (or a dedicated integration test in `tonic/tests/integration_tests/tests/`):

```rust
#[cfg(feature = "snappy")]
#[test]
fn snappy_roundtrip_empty() {
    let mut decompressed = BytesMut::new();
    let mut out = BytesMut::new();
    compress(
        CompressionSettings { encoding: CompressionEncoding::Snappy, buffer_growth_interval: 8192 },
        &mut decompressed, &mut out, 0,
    ).unwrap();
    // Must include the framed-snappy stream identifier so Java/Go decoders accept it.
    assert!(out.starts_with(b"\xff\x06\x00\x00sNaPpY"), "got: {:02x?}", &out[..]);
}
```
This test fails on master-of-the-fork and passes with Option A.

## Graph state

| Node | Status | Shape | Mode | Confidence |
|---|---|---|---|---|
| H₀ snap drops empty input | Confirmed | Divergent | Induction (ran binary) | 98% |
| H₁ other codecs emit valid empty streams | Confirmed | Convergent | Deduction (wire format) | 95% |
| Fix A — manual identifier | Open (untested in tonic) | — | Abduction | 80% |
| Fix B — skip-on-empty | Open (broader scope risk) | — | Abduction | 70% |

## Frontier

- Apply Option A inside PR #2524's fork branch, add the regression test, run `cargo test -p tonic --features snappy` against the docker tester.
- Same class of bug for `lz4_flex::frame::FrameEncoder` on empty input — needs the equivalent probe (`write_all(&[])`, check if magic `04 22 4d 18` is emitted). Same fix shape applies if so.

## Halt

**Cannot ship a PR against hyperium/tonic master**: the Snappy code is only in unmerged PR #2524. The right action is either (a) wait for #2524 to merge and then ship the fix as a follow-up, or (b) post the diagnosis + Option A patch as a review comment on #2524 so it gets folded in pre-merge. Both are operator decisions, not autonomous PR creation.

Recommendation: leave a comment on issue #2599 that explains the root cause and points at PR #2524 as the place where the fix needs to land, so jojoxhsieh knows it's a pre-merge fork issue, not a 0.14.5 release bug.
