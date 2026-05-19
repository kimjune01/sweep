# EnzymeAD/Enzyme.jl#3084 — Julia 1.13: `No augmented forward pass for ijl_enter_handler`

**Status**: halted at Phase 1 (maintainer self-report + no Julia 1.13 perturbation surface).

## H₀ (untested)

Julia 1.13 split the old `jl_push_handler` runtime call into a separate `ijl_enter_handler(current_task, handler)` lowering for `try` setup. Enzyme.jl's attribute pass tags the historical pair (`jl_push_handler` / `ijl_push_handler` plus the `jl_pop_handler*` variants) with the `enzyme_ReadOnlyOrThrow` string-attribute and the `nofree/nosync/nounwind/willreturn` quartet at `src/llvm/attributes.jl:692-720` and `:722-756`. Without an entry for the new `ijl_enter_handler` symbol, Enzyme's augmented-forward pass refuses to treat the call as opaque-but-safe and emits the reported `EnzymeNoDerivativeError: No augmented forward pass found for ijl_enter_handler`.

**Predicted minimal fix shape** (one-line audit, two new entries each in two existing lists):

```julia
# src/llvm/attributes.jl, inside the enzyme_ReadOnlyOrThrow block (~L698)
"ijl_push_handler",
"jl_push_handler",
"ijl_enter_handler",     # +
"jl_enter_handler",      # +

# and again inside the nofree/nosync/nounwind/willreturn block (~L745)
"ijl_push_handler",
"jl_push_handler",
"ijl_enter_handler",     # +
"jl_enter_handler",      # +
```

The reasoning is structural: `ijl_enter_handler` is the v1.13 name for the same exception-frame setup that `ijl_push_handler` performed on v1.12; semantics for AD are identical (sets a setjmp slot, does not write user-visible state, can throw). Mirroring `push_handler`'s attribute treatment should make the error go away.

## Why no fan-out / no PR

- **Reporter is `vchuravy`** — one of the two Enzyme.jl leads. Per `[[feedback_maintainer_self_pr]]`, halt: this is internal tracking from someone running the Julia 1.13-dev test suite against Enzyme. They have the IR, the failing function, and the lowering knowledge already.
- **No Julia 1.13 toolchain in the test container.** `sweep project-info` reports `test_env: docker:sweep-tester:latest`, which carries no Julia, let alone the 1.13-dev branch needed to even reproduce the `ijl_enter_handler` lowering. We cannot run the "fail on master, pass with fix" gate that [[project_fail_on_main_origin]] requires before shipping.
- **Single-codepath assumption unverified.** The fix above presumes `ijl_enter_handler` is a pure semantic rename of `ijl_push_handler`. If 1.13 also changed the signature (e.g., new state pointer the handler must propagate), the attribute-only fix won't be enough — Enzyme's type analysis might also need a new shadow-creation rule. Confirming requires reading Julia 1.13's `src/codegen.cpp` and `src/julia.h` for the new declaration, which is out of scope without a 1.13 checkout.
- **Adjacent symbols.** Issue mentions `@warn`-via-`try/catch` triggering the path. Julia 1.13 may also have renamed `jl_pop_handler` → `ijl_leave_handler` for symmetry; if so, the same attribute lists need both halves of the new pair, not just enter.

## Candidate edges (for the maintainer or whoever has a Julia 1.13 build)

1. **E₁: Pure-rename verification.** Compile a minimal `try / catch` snippet with Julia 1.13-dev, dump LLVM IR, confirm only `ijl_enter_handler` (and any `*_leave_handler` partner) is new. If yes → ship the one-line attribute additions above; rerun the `advanced` / `basic` tests.
2. **E₂: Type-analysis rule.** If the signature changed (extra ptr arg, return value), check whether Enzyme.jl needs a TypeAnalysis hook in `src/typeanalysis.jl` similar to existing handler entries, not just attribute tagging.
3. **E₃: Test-suite scope.** Beyond the two failures in the report (`advanced::No Decayed / GC`, `basic::Base functions::f25`), grep test/ for other `@warn` / `try` usages that may quietly start failing once Julia 1.13 lands.

## Provenance

- Issue: <https://github.com/EnzymeAD/Enzyme.jl/issues/3084>
- Attribute file pinpointed: `src/llvm/attributes.jl` (depth-50 clone @ HEAD `40e5fab`, 2026-05-18).
- Related symbols already handled: `jl_push_handler`, `ijl_push_handler`, `jl_pop_handler`, `ijl_pop_handler`, `jl_pop_handler_noexcept`, `ijl_pop_handler_noexcept`, `julia.except_enter`, `ijl_restore_excstack`, `jl_restore_excstack`.

## Reasoning mode

- H₀ root-cause: **abduction** (~75%). Read source, inferred Julia 1.13 rename from issue text; no induction (no 1.13 build available).
- Fix-shape sketch: **deduction** (~85%) conditional on H₀ being a pure rename. Drops to ~50% if signature changed.

## Halt

No PR. The hypothesis graph plus the two-list patch are the artifact; they sit here for the maintainer (or any future contributor with a Julia 1.13 toolchain) to validate and ship.

## Re-investigation 2026-05-18 (cycle 2)

Re-entered via `/investigate EnzymeAD/Enzyme.jl#3084`. State unchanged:

- `git log --all -- src/llvm/attributes.jl` since cycle 1: no new commits.
- `git log --all --grep="enter_handler|3084"`: no in-flight work, no related PR opened.
- `gh` context pack still shows zero related open PRs, zero prior PRs from `kimjune01` on this repo.
- `docker run --rm sweep-tester:latest sh -c "julia --version"` → `julia: not found` (exit 127). The fail-on-master/pass-on-fix invariant from [[project_fail_on_main_origin]] is still unsatisfiable; halt for the same reason.

H₀, H₁ (noexcept variant), H₂ (C++ rule) unchanged. No new edges to follow without a Julia 1.13 build. Graph remains the artifact.

