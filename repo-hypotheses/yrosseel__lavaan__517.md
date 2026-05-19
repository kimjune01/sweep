# yrosseel/lavaan#517 — `fitMeasures()` errors on SAM objects; `summary(fit.measures=TRUE)` warns

## H₀: SAM objects have everything needed for fit measures, they just aren't routed.

- **Perturbation (read code).** Trace what `joint@test`, `joint@optim`, `joint@Model`, and `joint@internal` look like after `sam(...)` returns.
- **Result.**
  - `joint@test <- step2$FIT.PA@test` (xxx_sam.R:354) — joint's test stat IS the structural-part test.
  - `joint@optim <- step2$FIT.PA@optim` (xxx_sam.R:353) — convergence flag is FIT.PA's.
  - `joint@Model` is the **joint** SEM model (mm + structural), not FIT.PA's model.
  - `object@internal$sam.struc.fit` is already a named numeric `c(chisq, df, cfi, rmsea, srmr)` from `fitMeasures(fit_pa, …)` (lav_sam_utils.R:708-717).
- **Classification.** Divergent for. The mismatch is between joint@test (structural-only) and joint@Model/baseline (full joint). `lav_fit_measures()` recomputes CFI/RMSEA using baseline-from-joint-model, which is wrong/blow-up territory. **The cached `sam.struc.fit` is already the right answer.**
- **Edge.** Two patches: (a) make `fitMeasures(SAM)` return the cached vector; (b) make `summary(SAM, fit.measures=TRUE)` not re-call `lav_fit_measures` because the SAM section already prints those values.

## H₁: The error path inside `lav_fit_measures()` is reachable but downstream of the cached values.

- **Perturbation (read code).** `lav_fit_measures()` early checks (lav_fit_measures.R:209-226) for `data.type=="none"`, `!converged`, `test=="none"` — none trigger for local SAM. Execution proceeds to baseline-model computation, which fails or warns for joint-model baseline of a SAM.
- **Classification.** Convergent — kills the "maybe one early check needs to flip" abduction. The fix must short-circuit *above* these checks.
- **Provenance.** `fitMeasures()` on a regular `lavaan` object works; SAM was added later (xxx_sam.R) and explicitly chose to call `fitMeasures` only on FIT.PA (lav_sam_utils.R:709), cache the 5 measures, and never re-route the generic. The maintainer's existing pattern — "5 measures, structural part only" — is the right shape for the fix.

## H₂: User wants the same 5 measures the print already shows.

- Quote from issue: *"given the selected fit measures printed under `Summary Information Structural part`, I believe some of them are officially supported for SAM"*.
- **Decision.** Surface exactly `sam.struc.fit` for SAM. Don't add new measures; don't silently degrade `fit.measures = "all"` to "everything we have"; do warn when caller asks for measures we can't supply.

## Diagnosis

- `fitMeasures(SAM)` → re-route to the cached `object@internal$sam.struc.fit`, filtered by requested `fit.measures`. Stop only if the cache itself was a try-error.
- `summary(SAM, fit.measures=TRUE)` → don't call `lav_fit_measures` (it would error, and the SAM section already prints the same values). Skip silently.
- `summary(SAM, fit.measures="all")` and `fitMeasures(SAM, "all")` → return the 5 cached measures; warn if specific requested measures aren't available.

## Fix shape

1. New helper `lav_sam_fit_measures()` in `R/lav_sam_utils.R` that filters/formats the cached vector per `fit_measures` and `output`.
2. In `R/lav_fit_measures.R::lav_fit_measures()`, short-circuit at the top: if `object@internal$sam.method %in% c("local","fsr","cfsr")`, delegate to the helper.
3. In `R/lav_object_summary.R`, in the `fit_measures != "none"` block, skip the `lav_fit_measures` call when the object is SAM (the structural-part fit is already in `res$sam$sam.struc.fit` and is printed by the SAM section).

## Provenance check

- The `sam.struc.fit` field has been the cache of structural-part fit measures since SAM was introduced (only commit visible in shallow clone).
- The maintainer's deliberate choice in `lav_sam_table` is "5 measures, structural part only, via fitMeasures(fit_pa)". Our fix honors that contract by surfacing the same 5 through the public API.
- No competing PRs in the pack (`Related open PRs: (none matched)`), no prior PRs by kimjune01 on this repo.

## Frontier edges

- (closed) **What about `sam.method = "global"`?** The cache stores a warning string for global; `fitMeasures(SAM-global)` should fall through to the regular path (joint object IS a regular lavaan fit in global mode). → Only short-circuit for local/fsr/cfsr.
- (open, low risk) Does `lav_fitmeasures_print` accept a 5-element vector cleanly when output="text"? — Yes, it's a `lavaan.vector`; the existing print path handles it.

## Reasoning modes

| Claim | Mode | Confidence |
|-------|------|-----------:|
| `joint@test` = FIT.PA's test (structural only) | Deduction (read xxx_sam.R:354) | 98% |
| `sam.struc.fit` is a named numeric vector with 5 measures | Deduction (lav_sam_utils.R:708-720) | 98% |
| Current `fitMeasures(SAM-local)` errors | Induction (issue reproducer) | 95% |
| Re-routing to cached fixes both `fitMeasures` and `summary` | Abduction → deductive trace | 85% |
| Global SAM unaffected by fix (cache holds a warning) | Deduction | 90% |
