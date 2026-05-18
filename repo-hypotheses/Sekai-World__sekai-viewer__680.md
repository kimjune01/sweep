# Hypothesis Graph: Sekai-World/sekai-viewer #680

**Issue:** "Blinking is not implemented for most characters in Live2d Story Reader"
**Reporter:** tracer4b (2026-05-12)
**Symptom:** In the Live2D Story Reader, most characters do not blink while idle. VBS Miku blinks. Motions that close the eyes still play normally.

## H₀ — Auto-blink is disabled per-model (abduction, ~70%)

- **Null:** Auto-blink should run for all models because pixi-live2d-display-mulmotion creates an `EyeBlink` controller from the model3.json `Groups[Name="EyeBlink"].Ids`.
- **Perturbation:** Fetch a sample of model3.json files from the live CDN (`storage.sekai.best/sekai-live2d-assets/`) and inspect `Groups[Name="EyeBlink"].Ids`.
- **Result:**
  - `v1/main/21_miku/21miku_normal/21miku_normal_3.0_f_t02.model3.json` → `Ids: ["ParamEyeROpen", "ParamEyeLOpen"]` (works → matches user's "VBS Miku blinks" anchor; "21miku" is the Virtual Singer Miku model).
  - `v2/main/21_miku/v2_21miku_band/21miku_leoneed2_t03.model3.json` → `Ids: []`.
  - `v1/main/21_miku/21miku_band/21miku_band_3.0_f_t01.model3.json` → `Ids: []`.
  - Random sample of 30 models from `model_list.json` (n=775): **30/30 had `Ids: []`**.
- **Trajectory:** Divergent in favor. The single working case has populated IDs; every broken case has empty IDs. The asymmetry of the random sample (0% populated) explains "most" in the bug title.
- **Shape:** Divergent → follow the edge.
- **Provenance:** `getModelData` in `src/utils/live2dLoader.ts:10-12` fetches the upstream model3.json verbatim and only rewrites `FileReferences.Motions` / `Expressions`; the `Groups` array passes through unchanged. The pixi-live2d-display-mulmotion library reads `Groups` to instantiate its `EyeBlink` controller. With `Ids: []`, the controller has no parameters to drive, so auto-blink is a no-op.
- **Why motion-driven eye-close still works:** motions write directly to `ParamEyeLOpen` / `ParamEyeROpen` via motion3.json curves. The library's blink controller only fights the idle path. So the user's observation "Animations during which eyes close work normally" is consistent.

**Status:** Confirmed. Root cause = upstream model3.json files ship with `EyeBlink.Ids: []` for ~all models except a handful of Virtual Singer normals.

## H₁ — Sub-hypothesis: standard Cubism 3 parameter names work on the affected models

- **Null:** Affected models might use non-standard parameter IDs for eye-open.
- **Evidence (deduction):** User states motion-driven eye-close works. The codebase's `reset_lipsync_param` (`Live2D.ts:154`) and the *single* working model both use the Cubism 3 standard names `ParamEyeLOpen` / `ParamEyeROpen` / `ParamMouthOpenY`. The motion `Expression` paths drive these same parameters on the same models (otherwise the eye-close animations the user describes wouldn't work). The pixi-live2d-display blink controller calls `setParameterValueById` — unknown IDs are silently ignored, so injection is safe even if a model happened to use different IDs.
- **Shape:** Convergent. Inject the standard IDs at load time.

## Fix

In `src/utils/live2dLoader.ts` `getModelData`, after the model3.json is fetched, ensure the `EyeBlink` group has populated IDs. If missing or empty, set the Cubism 3 standard pair.

```ts
// Patch upstream model3.json: most ship with an empty EyeBlink Ids array,
// which disables auto-blink in pixi-live2d-display-mulmotion (#680).
const EYE_BLINK_DEFAULT_IDS = ["ParamEyeROpen", "ParamEyeLOpen"];
if (!Array.isArray(model3Json.Groups)) model3Json.Groups = [];
const eyeBlink = model3Json.Groups.find(
  (g) => g.Target === "Parameter" && g.Name === "EyeBlink"
);
if (eyeBlink) {
  if (!eyeBlink.Ids || eyeBlink.Ids.length === 0) {
    eyeBlink.Ids = EYE_BLINK_DEFAULT_IDS as unknown as number[];
  }
} else {
  model3Json.Groups.push({
    Target: "Parameter",
    Name: "EyeBlink",
    Ids: EYE_BLINK_DEFAULT_IDS as unknown as number[],
  });
}
```

(Note: `ILive2DModelData.Groups[].Ids` is typed as `number[]` in `types.d.ts:1618`, but Live2D's actual schema is `string[]`; the existing working model proves this. The cast keeps the patch minimal — fixing the type is out of scope.)

## Frontier edges

- **F1:** Does `Live2D.tsx` (the zip packer) also need the IDs populated? It already hardcodes `Ids: []` at line 233 — same bug if the resulting zip is loaded by anyone using a stricter blink implementation. Out of scope for #680 (which is the Story Reader), but worth a follow-up.

## Reasoning mode table

| Claim | Mode | Confidence |
|---|---|---|
| Root cause is empty `EyeBlink.Ids` in upstream model3.json | Induction (30/30 sample + 1/1 working anchor) | 95% |
| Fix injection works for affected models | Deduction (motions write to same param IDs) + safe degradation if wrong | 90% |
| Generalizes beyond the sample | Induction + abduction (sample size 30, population 775) | 85% |

## Pruning log

None — the first hypothesis fit the evidence cleanly.
