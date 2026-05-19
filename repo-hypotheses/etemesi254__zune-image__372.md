# Hypothesis Graph: etemesi254/zune-image#372

**Issue**: Incorrect decoding / artifacts when opening APNG (woelper, 2026-04-11)
**Verdict**: HALT — maintainer shipped a structural fix the day before this investigation (ae97369a, 2026-05-17). No PR.
**Date**: 2026-05-18

## H0 (observation)

woelper reports APNG decoding artifacts in zune-png 0.5.2. Reproducer at https://github.com/woelper/apng_test uses the now-deprecated `post_process_image` function. Maintainer comment (2026-04-30) describes their own analysis: dispose_op=None vs output.fill(0) creates an oscillatory outcome — fixing one test image breaks another. Maintainer is asking the community for spec guidance ("I am not sure what to do, so if anyone has what is correct, would love some help").

Trajectory: **divergent against status-quo code** — the deprecated `post_process_image` applied `frame_info.dispose_op` (current frame's) before rendering, which is the wrong frame per APNG spec.

## H1 — Maintainer's recent ApngContext (ae97369a) corrects the disposal-ordering bug

**Perturbation**: Read `crates/zune-png/src/apng.rs` at HEAD. Compare to the version pasted in the issue body.

**Evidence**:
- New `ApngContext::process_frame` (lines 320-475) applies disposal based on `self.prev_frame_info.dispose_op` BEFORE rendering current frame, then backs up canvas if current frame requests `DisposeOp::Previous`, then bounds-checks, then blends. This matches the APNG spec ordering.
- The pasted code in the issue body uses `match frame_info.dispose_op` (current frame's) before render — the bug. That codepath is now in the deprecated `post_process_image` that returns an error.

**Trajectory**: **convergent** — the new code structurally fixes what the issue describes.

**Provenance**: ae97369a "png: Many fixes" (2026-05-17, etemesi254), bundled with fuzz-test resilience changes. Added two tests (`test_animation`, `test_animation_clock`) that hash-compare deterministic output but do NOT compare against a reference decoder.

## H2 — woelper's repro files 19.png and 2.png are not APNGs

**Perturbation**: Download woelper/apng_test files, dump chunk headers.

**Evidence**:
```
19.png: IHDR IDAT*5 IEND   ← static PNG, no acTL/fcTL
2.png:  IHDR IDAT*5 IEND   ← static PNG, no acTL/fcTL
ball.png (Wikipedia ref): IHDR acTL fcTL IDAT fcTL fdAT ...   ← APNG
```

`PngDecoder::more_frames` returns false when `actl_info` is None (decoder.rs:478), so woelper's `while decoder.more_frames()` loop body never ran for 19.png and 2.png. The artifacts woelper saw in screenshots were from the *output* path of his app for these files (encoded copies), not from APNG compositing. This means the "two test cases that disagree" the maintainer reasoned about may have been bootstrapped from non-APNG files in addition to the actual APNG (ball.png).

**Trajectory**: **divergent** — the reproducer set is mixed, and the maintainer's stated oscillation between "fill(0)" and "do nothing" was reasoning about the wrong test set in part.

## H3 — ApngContext on ball.png produces non-degenerate output

**Perturbation**: Write a Rust test using `ApngContext::<u8>::new` + `process_frame` loop on the Wikipedia reference APNG. Check that (a) `more_frames` yields >1 frame, (b) final canvas is not all-zero, (c) final canvas has at least one opaque alpha pixel (the symptom woelper flagged on 2026-04-14 was "alpha channel completely black/transparent").

**Result**:
```
test test_issue_372_bouncing_ball ... ok
```
- Loop produced multiple frames.
- Final canvas had non-zero RGB and at least one opaque alpha pixel.

**Trajectory**: **convergent** for ball.png. Does NOT prove pixel-level correctness vs a reference decoder — only that gross symptoms are absent.

## H4 (frontier, not pursued) — Pixel-level correctness vs reference decoder

Would require a reference APNG decoder that composites (png crate's `next_frame` only emits sub-frame raw pixels — compositing is caller responsibility, so the comparison would just be apples-to-apples between two implementations of the spec). To do this properly:
- Decode each frame with both zune ApngContext and a known-correct reference (image-rs's apng support, or imagemagick CLI), composite, diff per-pixel.
- Requires either pulling in `image` as dev-dep (heavy) or shelling out to `convert` (test env coupling).

**Not pursued because**:
1. Maintainer already shipped a structural fix 1 day before this investigation. Adding a thin regression test risks merge friction with their in-flight work.
2. Past triage in [[reference_no_llm_repos]] / repo-hypotheses correctly flagged this as SPEC_AMBIGUITY — a heavy-context case unsuitable for a first contribution. Our merged contribution to this repo so far is one mechanical fix (#392).
3. The maintainer's open question ("what is correct?") is a spec-interpretation discussion, not a code-shape question. The maintainer should drive it.

## Reasoning mode table

| Claim | Mode | Confidence |
|-------|------|-----------|
| New ApngContext applies disposal in spec-correct order | Deduction (read code) | 95% |
| 19.png and 2.png lack acTL/fcTL chunks | Induction (chunk dump) | 99% |
| ball.png decodes without gross symptoms | Induction (ran test) | 90% |
| Pixel-level correctness on ball.png | Untested | n/a |

## Decision

**HALT, do not ship a PR.** The maintainer has structural work in flight that addresses this issue. Our value-add of "regression test with hash assertion" would either duplicate `test_animation` (already in test_random.rs) or require deeper reference-decoder integration that the maintainer should choose, not us. The right move is to let the maintainer's ApngContext bake.

If the issue is still open in 2 weeks and the maintainer requests help, revisit with a focused reference-decoder comparison test and bring it as a draft PR they can pull in. Until then this is in their court.
