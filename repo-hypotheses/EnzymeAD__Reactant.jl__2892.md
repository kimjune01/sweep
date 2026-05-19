# EnzymeAD/Reactant.jl#2892 Hypothesis Graph

Issue: https://github.com/EnzymeAD/Reactant.jl/issues/2892
Title: `builtin.unrealized_conversion_cast` around `stablehlo.power` with multifloat
Started: 2026-05-18

## H₀ — `multi-float-conversion` MLIR pass is missing a rewrite for `stablehlo.power`

- **Mode**: deduction (read the failure MLIR + repo layout)
- **Observation**: post-pass IR shows `power` sandwiched between unrealized casts:
  ```
  %0 = builtin.unrealized_conversion_cast %cst_2 : tensor<2x4xf32> to tensor<4xf64>
  %1 = stablehlo.power %arg0, %0 : tensor<4xf64>
  %2 = builtin.unrealized_conversion_cast %1 : tensor<4xf64> to tensor<2x4xf32>
  ```
  Other ops in the same module (`add`, `subtract`, `reduce`, `concatenate`, `convert`) are lowered to f32 multi-limb expansions; only `power` is left in the original f64 surrounded by casts the pass never finalizes.
- **Reporter abduction** (dkytezab, comment): "Are we missing a conversion for `pow`? I see we have one for `exp`."
- **Provenance check**: pass is named `multi-float-conversion`. Source not in this repo.
  - `gh search code "multi-float-conversion" --owner EnzymeAD` →
    - `EnzymeAD/Enzyme-JAX:src/enzyme_ad/jax/Passes/MultiFloatConversion.cpp`
    - `EnzymeAD/Enzyme-JAX:src/enzyme_ad/jax/Passes/Passes.td` (`def MultiFloatConversionPass`)
    - test fixtures live under `EnzymeAD/Enzyme-JAX:test/lit_tests/multifloat/`
  - Inside Reactant.jl the only references are option-string construction (`src/CompileOptions.jl:10`) and pipeline invocation (`src/compiler/Compiler.jl:963-964`).
- **Status**: **confirmed for diagnosis, wrong-repo for fix**. The patch must add a `stablehlo.power` rewrite rule (modelled on the existing `exp` handler) in `EnzymeAD/Enzyme-JAX`, plus a lit test under `test/lit_tests/multifloat/`. Nothing in Reactant.jl needs to change.

## Decision

Halt the investigation in this repo. There is no actionable surface inside `EnzymeAD/Reactant.jl` — the C++ pass that owns this lowering lives in `EnzymeAD/Enzyme-JAX`. Routing to a Reactant.jl PR would touch nothing relevant and waste maintainer attention.

## Recommended next step (out of scope for this skill run)

If we want to ship the fix, re-enter `/investigate` against `EnzymeAD/Enzyme-JAX`, target `src/enzyme_ad/jax/Passes/MultiFloatConversion.cpp`, mirror the `exp` handler for `stablehlo.power`, and add a fixture under `test/lit_tests/multifloat/power.mlir`.

## Frontier

- (closed in this repo)
- open in Enzyme-JAX: which `exp` lowering shape to copy (Taylor series vs identity-on-limbs vs decomposition through `exp(b·log a)`)? Decisive perturbation is reading the existing `exp` case in `MultiFloatConversion.cpp` and matching the same structural pattern.
