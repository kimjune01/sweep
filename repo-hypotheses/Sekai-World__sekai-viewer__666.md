# Hypothesis graph: Sekai-World/sekai-viewer#666 — VIRTUAL SINGER partvoice files not loading

## H₀ — Observation

VIRTUAL SINGER (chara IDs 21-26: Miku, Rin, Len, Luka, Meiko, Kaito) partvoice files fail to load for most side stories. Airi's "Always Looking Ahead" part 1 is a noted exception.

## H₁ — `getTalkVoiceUrl` branch is wrong for VS characters

`src/utils/storyLoader.ts:872-900` (introduced d66cb02 by dnaroma 2025-10-27):

```ts
if (chara2d) {
  const chara = `${chara2d.assetName}_${chara2d.unit}`;
  if (chara.startsWith("v2_") || chara.startsWith("clb")) {
    // path A: sound/scenario/voice/part_voice_${chara}/${VoiceId}.mp3
  } else {
    // path B: sound/scenario/part_voice/${chara}/${VoiceId}.mp3
    // path C (if B null): sound/scenario/voice/part_voice_${chara}/${VoiceId}.mp3
  }
}
```

**Perturbation**: query the JP asset bucket directly for the `sound/scenario/voice/part_voice_` prefix listing.

**Result (induction, divergent)**: the directory namespace looks like

| Prefix in bucket                  | Exists for VS units                                                          |
|----------------------------------|------------------------------------------------------------------------------|
| `part_voice_<id>_<unit>/`        | `21miku_idol`, `21miku_piapro` only                                          |
| `part_voice_v2_<id>_<unit>/`     | every VS × every unit (incl. light_sound, street, school_refusal, theme_park)|
| `part_voice_clb01_<id>_<unit>/`  | colorful palette collab variants                                             |

VIRTUAL SINGER chara2d entries have `assetName = "21miku"` (etc.) — NOT `v2_`-prefixed. So `chara = "21miku_light_sound"` does NOT start with `v2_` or `clb`. It falls into the else branch, which only tries `21miku_light_sound` (no `v2_` prefix). **That directory does not exist** for any unit other than `idol`/`piapro`.

This precisely explains:
- Almost every side story fails (VS appears in light_sound/street/school_refusal/theme_park unit stories).
- Airi's "Always Looking Ahead" works — VS appearances in MMJ-driven stories use the `idol` unit, which is one of the only two `part_voice_<id>_<unit>/` directories that exist without a `v2_` prefix.

**Status: confirmed (divergent).**

## Provenance

- Origin commit: d66cb02 `fix(live2d): enhanced model name processing` (dnaroma, 2025-10-27). The author's own inline comment lists three paths to check; the v2/clb branch stops at path 1 and the non-v2 branch never tries the `v2_`-prefixed directory.
- Commented-out `errorVoices` line (`voiceFinder.ts:6-10`) shows the author already knew real files live at `part_voice_v2_24luka_light_sound/` — exactly the case the new code misses.

## Fix shape

Add a fallback for the non-v2/clb branch: after the two existing attempts, try `sound/scenario/voice/part_voice_v2_${chara}/${VoiceId}.mp3`. This covers VS characters whose `assetName` lacks the `v2_` prefix even though their assets live in `v2_`-prefixed directories.

## Reasoning mode table

| Claim                                                       | Mode                  | Confidence |
|-------------------------------------------------------------|-----------------------|------------|
| chara2d.assetName for VS is bare (`21miku`)                 | induction (master DB) | 99%        |
| `part_voice_v2_<id>_<unit>/` exists for all VS×unit         | induction (S3 listing)| 99%        |
| `part_voice_<id>_<unit>/` only exists for idol/piapro       | induction (S3 listing)| 95%        |
| Adding the v2_-prefixed fallback restores VS voice loading  | deduction             | 90%        |
