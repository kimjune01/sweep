# Hypothesis graph: etemesi254/zune-image#395 (S1 — PSD 16-bit endianness)

Issue is a Claude-Code review report enumerating many findings. Maintainer responded:
- "small fixes can be PR'd its a lot of work to do them manually"
- Called out S1 (PSD endianness) by name as an example worth PRing
- "And better if we can add tests while at it"
- Already pushed `proj-fixes-claude` branch covering J8/C2/P11; PSD untouched

So scope = S1 only. Single fix, single test, small PR.

## H₀ — `decode()` byte-swaps every 16-bit sample on LE hosts

**Source path traced** (`crates/zune-psd/src/decoder.rs`):

| Step | Line | Operation |
|------|------|-----------|
| Read from PSD stream (BE on disk) | 436 | `get_u16_be_err()` returns correct native `u16` (e.g. `0x1234`) |
| Write to raw buffer | 437 | `chunk[..2].copy_from_slice(&value.to_ne_bytes())` → on LE, buffer holds `[0x34, 0x12]` |
| `decode()` reads back | 556 | `u16::from_be_bytes([0x34, 0x12])` → `0x3412` (byte-swapped) |

**Perturbation:** byte-by-byte mental trace above on LE host.
**Trajectory:** divergent — every 16-bit sample is provably wrong on every little-endian host (x86_64, aarch64). Confirmed.

## H₁ — white-matte 16-bit loop also operates on byte-swapped values

In the same function, lines 462-484 (`BitDepth::Sixteen` matte branch) read with `u16::from_be_bytes` from the buffer that line 437 just populated with `to_ne_bytes`. So:
- Alpha threshold check (`a != 0 && a != 65535`) tests against a swapped value — only `0xFFFF` (palindrome) is correctly identified.
- Color premultiplication math runs on swapped channels and writes swapped results back.

**Trajectory:** divergent. The matte step is broken in the same direction as `decode()`. Both must be fixed together or matte output remains garbage even after the `decode()` fix.

## Fix shape

Two consistent options:

**Option A** — write `to_be_bytes` everywhere in `decode_into`. Buffer holds on-disk BE bytes end-to-end. Changes `decode_raw`'s documented "native endian" contract (docstring lines 230, 364).

**Option C** (chosen) — keep `to_ne_bytes` writes (preserves the documented native-endian contract of `decode_raw`); change the *reads* to `from_ne_bytes` in two places: the matte loop (4 reads) and `decode()` (1 read). Five `_be_bytes` → `_ne_bytes` swaps, no contract change.

Going with C because it preserves the public contract of `decode_raw` for any external callers, and the diff is local to the read sites.

## Regression test

`crates/zune-psd/tests/test_endianness.rs` — decodes the existing `test-images/psd/rgb_16bits_image.psd`, compares `decode()` output to `decode_raw()` re-interpreted as native `u16`. They must agree (and currently don't on LE).

- **On master:** `decode_raw` produces native-endian bytes; `decode` reads them as big-endian → mismatch → fail.
- **On fix:** both interpret as native → match → pass.

## Provenance

- `decode()` 16-bit path was added in commit referenced by line 551's comment (`https://github.com/etemesi254/zune-image/issues/36`).
- Reporter (qarmin) is the same person who runs Claude-Code reviews across many Rust repos; their reports are credible but per their own caveat require validation. S1 was validated above.
- Maintainer's `proj-fixes-claude` branch touches jpeg/png/sse41 — PSD is open territory.

## Frontier

Closed for this PR. Other findings (J2 succ_high, IP6 orientation 7, I3 doc swap, I7 perf) are separate PRs and not in scope here.
