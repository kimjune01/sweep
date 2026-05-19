# Hypothesis Graph: etemesi254/zune-image#384

**Issue:** Out of memory panic when processing crafted PNG with bogus IHDR dimensions (16777288 × 16711752). Reporter (qarmin) used `Image::read` with each of `new_fast() / new_cmd() / new_safe()`. ASan reported a 558 TB allocation request.

**Maintainer signal (etemesi254):** "Is this in the latest git pull?" — the maintainer suspects it may already be fixed.

## H₀ — file triggers OOM on current dev with stock options

- **Null:** PNG decoder rejects the file before allocating the output buffer.
- **Perturbation:** Build a minimal repro (`Image::read(ZCursor::new(&bytes), opts)`) against `dev @ ac8e49b` (zune-image 0.5.0 / zune-png 0.5.2 / zune-core 0.5.1). Run with each of `new_fast`, `new_cmd`, `new_safe`. Measure RSS.
- **Result:** all three options return `Err("Image width 16777288, larger than maximum configured width 16384, aborting")`. Peak RSS 1.7 MB. No allocation attempt.
- **Trajectory:** divergent — null confirmed across all three option presets.
- **Kill condition:** the bug is not reproducible on current dev.
- **Mode:** induction. Confidence 95%.
- **Edge → H₁** (does it reproduce on the published crate version qarmin most likely consumed?).

## H₁ — OOM reproduces against published 0.5.x on crates.io

- **Null:** crates.io 0.5.0 also rejects via the IHDR width guard.
- **Perturbation:** rebuild the same repro against `zune-image = "0.5.0"`, `zune-core = "0.5"` from crates.io (resolved → zune-png 0.5.2, zune-core 0.5.1 — same code as dev for this path). Run with all three option presets.
- **Result:** identical rejection error, identical 1.7 MB peak RSS.
- **Trajectory:** divergent — null confirmed.
- **Kill condition:** the published crate also already enforces the limit.
- **Mode:** induction. Confidence 95%.
- **Edge → H₂** (where does qarmin's OOM come from, then?).

## Provenance check (H₀, H₁)

- `git blame` on `crates/zune-png/src/headers/readers.rs:37-50` (the `max_width` / `max_height` guard): introduced in `768a1534 png: Initial encoder.` in 2023. The guard predates the bug report by ~2 years.
- Default `DecoderOptions::max_width = max_height = 1 << 14 = 16384` (`crates/zune-core/src/options/decoder.rs:721`). `new_cmd()` only flips decoder flags via `set_decoder_flags(cmd_options())`; it does **not** clear `max_width`/`max_height`.
- delins's comment ("doesn't set limits by default") is factually incorrect: limits are set by default and apply uniformly to `new_fast / new_cmd / new_safe`.

## H₂ — qarmin's harness overrides `set_max_width(usize::MAX)` (open)

- **Null:** qarmin's fuzz harness disables the size cap (a common pattern for image-format fuzzers so they don't false-negative on legit large inputs).
- **Predicted perturbation:** ask qarmin for the exact `DecoderOptions` (and zune-image version) used in the reproducer.
- **Predicted trajectory:** convergent — likely a custom `set_max_width`/`set_max_height` lift, which would explain why ASan saw the 558 TB allocation request.
- **Status:** frontier edge. Cannot run without input from the reporter.
- **Mode:** abduction. Confidence 70%.

## Graph state

| Node | Status | Shape | Mode |
|------|--------|-------|------|
| H₀ | killed | divergent | induction |
| H₁ | killed | divergent | induction |
| H₂ | open (needs reporter input) | predicted convergent | abduction |

## Frontier edges

- **H₂:** ask qarmin for the exact `DecoderOptions` (with any `set_max_*` calls) and the zune-image version. Until that answers, no code change is justified.

## Pruning log

- H₀ killed: reproducing on dev with all three stock option presets returns a clean `Err` and ~1.7 MB RSS.
- H₁ killed: same outcome against `zune-image = "0.5.0"` from crates.io.
- delins's "doesn't set limits by default" claim killed by reading `decoder.rs:721`.

## Recommendation (no PR)

No code change is warranted. The IHDR guard already rejects the crafted file under all three stock option presets, on both `dev` and the most recent published crate. The right next action is a maintainer-facing comment confirming non-reproduction and asking qarmin for the harness's exact `DecoderOptions` and version, so we can either close the issue or identify the missing guard (likely on the path where the limit has been explicitly disabled).

### Draft comment (for `comment-issue` actor, awaiting operator)

> Cannot reproduce on `dev @ ac8e49b` or against `zune-image = "0.5.0"` from crates.io with the attached file. All three option presets (`new_fast`, `new_cmd`, `new_safe`) reject the file with `Image width 16777288, larger than maximum configured width 16384, aborting` and peak RSS stays at ~1.7 MB — no allocation attempt occurs. The `max_width` / `max_height` guard in `parse_ihdr` (`crates/zune-png/src/headers/readers.rs:37`) has been in place since the initial PNG encoder commit, and the defaults (`1 << 14`) apply uniformly to `new_cmd` as well (`new_cmd` only flips decoder flags, not size caps). Could you share the exact `DecoderOptions` your harness builds (any `set_max_width` / `set_max_height` calls?) and the zune-image version you saw the OOM on? That will tell us whether there's a different path that bypasses the IHDR guard or whether the harness lifted the cap.
