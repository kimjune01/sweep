# Hypothesis Graph: orottier/web-audio-api-rs#577

**Issue**: Low MediaStreamTrack sample rates crackle through create_media_stream_source

## H₀ — observation

User feeds a synthetic `MediaStreamTrack` of 128-sample chunks @ 8 kHz into `AudioContext::create_media_stream_source`. The AudioContext default sample rate on most hosts is 44.1 / 48 kHz. Output crackles audibly; `AudioRenderCapacity` stays low (no underrun). Crackle is periodic / persistent — not a one-shot artifact.

Provenance: user repro in issue body. **Induction**, confidence 95%.

## H₁ — per-chunk resample loses continuity at chunk boundaries

**Claim**: `Resampler::next` in `src/resampling.rs:67-110` pulls one input `AudioBuffer` at a time and calls `data.resample(self.sample_rate)` on **each chunk independently** (line 73, line 97). The `AudioBuffer::resample` function (`src/buffer.rs:311-363`) is stateless — it linearly interpolates over the chunk's own `[0, source_length-1]` and produces `[0, target_length-1]`. There is no carry of the previous chunk's tail sample.

For the repro (source 8 kHz → target 48 kHz, source_length=128, ratio=6):

- Within a chunk: `target_length = ceil(128 * 6) = 768`. Playhead step in source-space per output sample = `(source_length-1)/(target_length-1) = 127/767 ≈ 0.1655`.
- Across the chunk boundary: output sample `767` of chunk N corresponds exactly to source sample 127 of chunk N; output sample `0` of chunk N+1 corresponds exactly to source sample 0 of chunk N+1 (= source sample 128 in the continuous stream). One output-sample step suddenly advances a full source sample (≈ 0.1667 step, but more importantly without interpolation from N's tail).
- The within-chunk step (~0.1655) is slightly *smaller* than the ideal continuous step (1/ratio = 0.1667). The error accumulates inside the chunk, then snaps back at the boundary.

Result: a periodic phase discontinuity every `source_length / source_sr = 128 / 8000 = 16 ms = 62.5 Hz`. That matches the "buzz/crackle" character at 8 kHz input.

**Perturbation (deduction, code-traced)**: read `Resampler::next` and `AudioBuffer::resample`. No state is preserved across calls. The chunk is the resample window.

**Null**: if resampling were continuous (stateful, carrying the previous chunk's last sample as the interpolation predecessor for the first sample of the next chunk, with a fractional sub-sample offset), no boundary discontinuity would exist; the only error would be the interpolation noise floor (acceptable for linear interp).

**Trajectory**: **divergent toward H₁** — code inspection is decisive. The only way H₁ would be wrong is if some upstream code already smooths chunks before calling `resample`. Searched: `MediaStreamRenderer` (`src/node/mod.rs:77-`) feeds the `Resampler` output straight to `output.set_number_of_channels`; no inter-chunk smoothing.

**Provenance**: `git blame src/resampling.rs` — the per-chunk `data.resample(self.sample_rate)` call has been there since the file was authored; `AudioBuffer::resample` was added as a simple linear interp. No prior issue/PR explicitly addresses this boundary-discontinuity case. The closest related work was #589 / #590 (validating sample rate at context construction) — a different bug.

**Confidence**: 90% (deduction from code reading; induction step would be writing the test below to confirm the click rate matches the chunk-boundary period).

## H₂ — equal-rate path is fine (control)

When source_sr ≈ target_sr (within 0.1 abs), `AudioBuffer::resample` short-circuits (`src/buffer.rs:315-318`). No resampling, no boundary problem. That's why the issue only manifests at *low* MediaStreamTrack sample rates: the further from context rate, the more output samples per source sample, the more audible the boundary jump.

**Trajectory**: convergent control — predicts that running the repro with `SAMPLE_RATE = context.sample_rate()` makes the crackle disappear.

## Fix shape

The minimal fix is to make `Resampler` stateful: carry the previous chunk's **last source sample** and a fractional sub-sample offset (playhead-modulo-1) into the next chunk, and use them as the interpolation predecessor for that chunk's output. Equivalent: treat the input as a single continuous stream and the playhead as a `f64` that advances by `source_sr / target_sr` per output sample, looking up samples by absolute index across chunks.

Sketch:
- Move the resampling out of `AudioBuffer::resample` (stateless) and into `Resampler` (stateful).
- Keep a `last_source_sample: Vec<f32>` (one per channel) and a `playhead_frac: f64` across `next()` calls.
- Per output sample: integer-index into either `last_source_sample` (if `playhead_frac < 1` and we haven't consumed any of the new chunk yet) or the current source chunk, then advance by `source_sr / target_sr`.
- Pull new input chunks when `playhead_frac` advances past current chunk length; preserve the tail sample for the next call.

This is a non-trivial refactor — perhaps 40-80 lines, and it touches a hot path used by both `MediaElementAudioSourceNode` and `MediaStreamAudioSourceNode`. Wants careful tests:
- existing `test_resampler_concat` / `test_resampler_split` (which use same-rate input, no resample) must still pass
- new test: 8 kHz → 48 kHz repeating ramp `[0,1,2,…,127]` across N chunks should produce monotonically increasing output with no period-128-source-sample jumps in the second derivative

## Frontier

- **Open**: write the failing test (sine-input → check max sample-to-sample delta in resampled output is bounded; on master the boundary jump exceeds the within-chunk delta by a factor of ~6, on fix they should be comparable). Run on master to confirm; this is the induction step that turns H₁ from 90% deduction to 99%.
- **Open**: pick the implementation shape. Two options:
  1. Stateful linear interp in `Resampler` (minimal, matches existing quality).
  2. Pull in a real resampler (`rubato`) for higher quality. **Rejected for now**: scope creep, new dep, the maintainer hasn't asked for SRC quality, just non-crackling output.
- **Open**: the user reported via repro; the fix is non-trivial. Worth posting a brief tissue-style comment confirming the diagnosis before sinking the prework cost.

## Reasoning mode table

| Claim | Mode | Confidence |
|---|---|---|
| `Resampler::next` calls `data.resample` per chunk | Deduction (code read) | 99% |
| `AudioBuffer::resample` is stateless and re-anchors playhead per chunk | Deduction (code read) | 99% |
| Period of artifact = source_length / source_sr | Deduction (math from above) | 95% |
| Audible crackle = these boundary discontinuities | Abduction | 80% |
| Fix shape (stateful Resampler) eliminates the crackle | Abduction | 75% |

## Next step

This investigation lands at **diagnosis**, not at a one-liner fix. The fix is meaningful refactor. Stopping here and emitting a tissue comment (substrate routes to /tissue) with the diagnosis, so the maintainer can confirm before we sink the prework cost — or hand off to them if they want to write it.
