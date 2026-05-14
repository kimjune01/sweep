# FyroxEngine/Fyrox PR #918 — Hypothesis Graph

PR: https://github.com/FyroxEngine/Fyrox/pull/918
Branch: `fix/read-pixels-manually-drop` (fork: kimjune01/Fyrox)
Closes: #827
Subsystem: `fyrox-graphics/src/framebuffer.rs` — runtime/library (GPU framebuffer pixel readback). Pure data-layout safety, not editor UI or visual render output. GUI carve-out does not apply.

## Reviewer ask

@mrDIMAS, 2026-05-13 18:53 UTC, CHANGES_REQUESTED on commit f7f84f4. Single inline comment on framebuffer.rs:335:

> `.to_vec` call is kinda concerning here, I'm pretty sure that this can be done without calling it. Probably by creating a proxy struct that keeps the memory layout like in here — fyrox-impl/src/scene/mesh/buffer.rs#L269-L277

Concrete asks:
1. Eliminate the extra `.to_vec()` allocation/copy.
2. Use a proxy struct that preserves the original memory layout (mirror `BytesStorage` in `mesh/buffer.rs`).

No issue comments. No other reviewers.

## Hypotheses

### H1: The `.to_vec()` copy can be eliminated by changing the return type

- **Predicate:** A wrapper struct owning `Vec<u8>` and exposing `&[T]` via Deref avoids the copy while preserving correct dealloc layout.
- **Test:** Construct `TypedPixels<T> { bytes: Vec<u8>, _marker: PhantomData<T> }`. Implement `Deref<Target = [T]>` via `bytemuck::cast_slice`. Verify caller works via deref coercion.
- **Outcome:** CONFIRMED. Caller is `fyrox-impl/src/renderer/hdr/mod.rs:207` using `&pixels` against `fn average_luminance(self, data: &[f32])`. Deref coercion `&TypedPixels<f32>` → `&[f32]` applies; no caller change needed. `cargo check -p fyrox-impl` passes.

### H2: The `BytesStorage` pattern requires storing an explicit `Layout`

- **Predicate:** Need to store `Layout` alongside the bytes (as `BytesStorage` does at `mesh/buffer.rs:269-277`).
- **Test:** Inspect why `BytesStorage` keeps `layout: Layout`. It does so because it later calls `Vec::from_raw_parts(... cap)` and re-deallocates manually with the original layout — the layout is consumed by the explicit dealloc path, not by the `Vec<u8>` itself.
- **Outcome:** PARTIALLY FALSIFIED. In our case, the `Vec<u8>` is never decomposed; it is dropped as `Vec<u8>`, which by definition uses `Layout::array::<u8>(cap)`. Storing the layout separately would be redundant. mrDIMAS's pointer to `BytesStorage` is correct in spirit (own the buffer, preserve its dealloc) but the explicit `Layout` field isn't needed when the wrapper keeps the `Vec<u8>` intact. The proxy struct is the kernel of the suggestion; the `Layout` field is bookkeeping that matters only when re-decomposing.

### H3: `bytemuck::cast_slice` panics at runtime for the live caller

- **Predicate:** `cast_slice::<u8, T>(&bytes)` asserts `bytes.as_ptr() % align_of::<T>() == 0`.
- **Test:** Only caller uses `T = f32` (align 4). Rust's global allocator returns at least pointer-aligned blocks (≥ 8 on 64-bit) for any non-zero allocation backing a `Vec<u8>` from `read_pixels`.
- **Outcome:** REFUTED in practice for the current caller set. Same constraint already existed in the prior `.to_vec()` PR — not regressed by this change. If a future caller uses a higher-align type and a tiny allocation (which on some allocators gets sub-pointer alignment), `cast_slice` will panic loudly (not UB). Acceptable.

## Fix

Commit `1d26960` on `fix/read-pixels-manually-drop`. Diff: +51/-5 in `fyrox-graphics/src/framebuffer.rs`. Adds `TypedPixels<T: Pod>` wrapper with `as_slice`, `len`, `is_empty`, and `Deref<Target = [T]>`. Changes `read_pixels_of_type` return type from `Option<Vec<T>>` to `Option<TypedPixels<T>>`. Caller compiles unchanged via deref coercion.

## Verification

- `cargo check -p fyrox-graphics` — clean.
- `cargo check -p fyrox-impl` — clean (covers the one HDR caller).
- No new dependencies (`bytemuck` already present).
