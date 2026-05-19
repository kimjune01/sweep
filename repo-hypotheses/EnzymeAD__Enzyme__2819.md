# EnzymeAD/Enzyme#2819 — TypeAnalysis: seed extractvalue from LLVM type

PR: https://github.com/EnzymeAD/Enzyme/pull/2819
Issue: #2630 (crash on opaque-return extractvalue aggregates)
Branch: `fix/2630-extractvalue-type-deduction` @ e30d9d7f
Maintainer: @wsmoses

## H0 — fix belongs in TypeAnalysis.cpp::visitExtractValueInst (current PR)

- **Hypothesis**: When `looseTypeAnalysis` is on and the extractvalue source aggregate has no prior type info, seed the result type from the LLVM type if it has uniform FP leaves. Implemented as a `uniformFPLeafType` helper called inside `visitExtractValueInst` before the normal UP/DOWN propagation.
- **Perturbation**: Pushed PR with the seeding inside TypeAnalysis.cpp; gated behind `looseTypeAnalysis`; emits warning via `EnzymeTypeWarning`.
- **Trajectory**: **Divergent against** — maintainer review 2026-05-14 (TypeAnalysis.cpp:2828):
  > "you shouldn't modify typeanalysis itself for a loosetypeanalysis change, but the user instruction, if no type was found"
- **Kill condition**: Architectural objection — `looseTypeAnalysis` is a consumer-site policy; TypeAnalysis core should remain a pure dataflow analysis. The fallback belongs where the result is consumed (AdjointGenerator), not where types are computed.
- **Edge**: H1 — move the fallback to `AdjointGenerator.h:1894`.

## H1 — extend the existing loose-types fallback in AdjointGenerator.h

- **Hypothesis**: `AdjointGenerator.h:1894-1903` already has a `looseTypeAnalysis` fallback for the "Cannot deduce type of extract" path, but it only handles primitive FP/vector and Int/Pointer cases:
  ```cpp
  if (EVI.getType()->isFPOrFPVectorTy()) { dt = ConcreteType(...->getScalarType()); found = true; }
  else if (EVI.getType()->isIntOrIntVectorTy() || EVI.getType()->isPointerTy()) { dt = BaseType::Integer; found = true; }
  ```
  Crash #2630 happens because the extractvalue result is an aggregate (`[2 x float]`, `[2 x [3 x float]]`) which fails both predicates and falls through to `EmitNoTypeError`. Extending the FP branch to walk aggregate leaves (the `uniformFPLeafType` recursion) handles this case at the consumer.
- **Perturbation**: Revert TypeAnalysis.cpp changes; add `uniformFPLeafType` helper or inline equivalent in AdjointGenerator.h; extend the loose-types branch to call it for aggregate types; warning stays (matches existing `EmitNoTypeError` register).
- **Predicted trajectory**: Convergent — the maintainer named this location; the existing fallback already justifies the warning/error register; the test stays focused on the enzyme pass (drop the print-type-analysis WARN check since seeding no longer happens during analysis).
- **Status**: pending implementation.

## Provenance

- `looseTypeAnalysis` fallback at AdjointGenerator.h:1894 was added by wsmoses; the FP-or-Int restriction is deliberate (primitive-only by design).
- The "user instruction" framing in the review comment refers to enzyme's policy that `looseTypeAnalysis` is a user-supplied permission; it should not bleed into TypeAnalysis dataflow.
- Author's previous comment ("Scope: stayed away from AdjointGenerator.h:1894 primitive-only fallback") confirms the location was identified but deliberately skipped — that scope choice was the wrong one.

## Reasoning mode

| Claim | Mode | Confidence |
|-------|------|------------|
| H0 killed by maintainer redirect | Induction (review evidence) | 99% |
| H1 site is correct | Deduction (review comment names location implicitly via "user instruction, if no type was found") | 90% |
| Aggregate walker reuses uniformFPLeafType logic | Deduction (same predicate works) | 95% |

## Frontier

- Apply H1 patch; verify test still fails on master and passes with fix; push amend commit.
