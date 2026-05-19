# Hypothesis graph: etemesi254/zune-image#361

Panic `Option::unwrap() on a None value` at `crates/zune-jpeg/src/idct/avx2.rs:379` when decoding fuzz sample `cd6b8b2…txt` (200x192 baseline JPEG). Maintainer applied a partial stopgap (commit `3330a8eb`, 2026-03-11) released in 0.5.13; says "haven't fixed it to my satisfaction" — root cause is upstream stride/buffer divergence vs libjpeg-turbo.

Current crate version on `dev`: **0.5.15**. Sample still panics on x86_64 (the avx2 path).

## H₀ — Stopgap on avx2 `permute_store!` macro covered the first store only

- **Hypothesis.** The `unwrap_or(&mut tmp)` defense in `permute_store!` was applied to the first of two `_mm_storeu_si128` writes in the macro body; the second write (and the unrelated `store!` macro in the zero-AC fast path) still call `.unwrap()`.
- **Perturbation.** Read `crates/zune-jpeg/src/idct/avx2.rs` lines 47-78 (macro body) and 137-150 (zero-AC `store!`). Compare against commit `3330a8eb` diff.
- **Result.**
  - Line 60-61 (first store): `.get_mut($index..$index + 8).unwrap_or(&mut tmp)` — patched.
  - Line 70-71 (second store, after `$index += $stride`): `.get_mut($index..$index + 8).unwrap()` — **NOT patched**.
  - Line 142-143 (zero-AC `store!` macro, called 8x): `.get_mut($pos..$pos + 8).unwrap()` — **NOT patched**.
  - `neon.rs` and `scalar.rs` had both store sites patched in the same commit; only avx2.rs was left half-done.
- **Trajectory.** Divergent — code grep is decisive.
- **Kill condition.** Read evidence contradicts → killed in favour of "stopgap is incomplete, the missed sites match the reported panic location."
- **Mode.** Deduction (reading source), confidence 98%.

## H₁ — Reported panic at avx2.rs:379 is the second store in the macro

- **Hypothesis.** Line 379 is `permute_store!((row6.mm256), (row7.mm256), pos, out_vector, stride);` — the final macro invocation in `idct_avx2`. The panic line is the macro call site (Rust attributes the unwrap line to the call). Of the two unwraps in the expansion, only the second can panic (first uses `unwrap_or`). After the seventh `pos += stride` increment, if `out_vector.len() < pos + 8`, the unwrap on the second store fires.
- **Perturbation.** Trace: by line 379 the macro has been called 4 times = 8 stores = 7 `pos += stride` increments. For an 8x8 block, `pos` starts at 0 and reaches `7*stride`. If `out_vector` was sized assuming a smaller stride / different block layout (the libjpeg-turbo divergence the maintainer mentions), the 8th store overruns.
- **Trajectory.** Convergent — explains the line attribution and matches the maintainer's "stopgap" framing.
- **Mode.** Deduction, confidence 92%.

## H₂ — On aarch64 the same sample decodes cleanly because NEON stopgap is complete

- **Perturbation.** Built the sample against zune-jpeg dev HEAD inside the `sweep-tester` aarch64 docker image; ran the decoder.
- **Result.** `ok: 115200 bytes` (= 200×192×3, matches JFIF header). No panic. NEON path took the stopgap from commit `3330a8eb`, which patched both store sites in `idct_neon`.
- **Trajectory.** Divergent — confirms the avx2-only theory.
- **Mode.** Induction, confidence 95%.

## H₃ — Root cause is upstream (stride/buffer-size divergence vs libjpeg-turbo)

- **Hypothesis.** Maintainer's commit message: "Still investigating why we diverge from what libjpeg-turbo is doing." A proper fix would correct the stride or the `out_vector` allocation in the caller (likely `mcu.rs` or `mcu_prog.rs`). The unwrap is just where the symptom surfaces.
- **Status.** **Open / out of scope.** Maintainer is "still investigating"; PR #396 from another contributor is doing adjacent rework of scan replay but does not touch this. Attempting an upstream fix would race the maintainer and is non-trivial.
- **Edge.** Mirror the maintainer's existing stopgap pattern to the two missed sites in avx2.rs. Use the identical `unwrap_or(&mut tmp)` shape with the same `to prevent some bad images from crashing` comment style. Frame the PR as "complete the partial stopgap from 3330a8eb on x86_64." Maintainer is free to revert when the proper fix lands.

## Provenance

- Stopgap origin: commit `3330a8eb06603bdee4d205e78830afb1166ad12c` (2026-03-11), released in 0.5.13.
- Pattern is the maintainer's: `unwrap_or(&mut tmp)` with `let mut tmp = [0;8];` declared in the macro body.
- `neon.rs` (lines 102-115 and 212-235) and `scalar.rs` (lines 159-167 and 268-285) carry the same pattern at both store sites — avx2 is the lone holdout.
- Issue #362 (referenced in the stopgap comment in `mcu.rs`) is the sibling-track bug for the same fuzz batch.

## Frontier edges

- `e1`: file a PR that applies `unwrap_or(&mut tmp)` to both missed avx2 sites (second store in `permute_store!`, both unwraps in zero-AC `store!`). Convention: identical to the maintainer's existing patches in `neon.rs` and `scalar.rs`.
- `e2`: add a regression test using the published fuzz sample (`cd6b8b2…`) checking that decode returns either Ok or a `DecodeErrors` variant — never panics. Sample is small (3.8KB) and the issue reporter explicitly authorized its inclusion in the fuzz corpus.

## State table

| H | Status | Shape | Mode | Confidence |
|---|--------|-------|------|------------|
| H₀ | confirmed | divergent | deduction | 98% |
| H₁ | confirmed | convergent | deduction | 92% |
| H₂ | confirmed | divergent | induction | 95% |
| H₃ | open (maintainer-owned) | n/a | abduction | 70% |

## Pruning log

- (none — all four nodes survived; H₃ deferred to maintainer.)
