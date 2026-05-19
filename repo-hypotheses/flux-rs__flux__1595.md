# flux-rs/flux#1595 — Hypothesis Graph

PR: https://github.com/flux-rs/flux/pull/1595
Issue: https://github.com/flux-rs/flux/issues/833 — "Check that the self type in an extern spec for a trait impl matches the external definition"
Author: kimjune01 (self-PR)
Status: OPEN, CI FAILING (tests + vtock + lean-demo, 111 compile errors in `flux-core`)

## H₀ — Baseline (observation)

**Hypothesis:** The PR adds `check_extern_impl_self_ty` that compares the local impl's self type to the extern impl's self type via `tcx.type_of(local_id).instantiate_identity() != tcx.type_of(extern_impl_id).instantiate_identity()`.

**Perturbation:** Run CI on the branch.

**Result:** 111 errors. Sample:
```
self type `convert::num::ptr_try_from_impls::_::__FluxExternImplStructTryFromi128`
   doesn't match the external trait impl
external trait impl has self type `i128`
```
Every legitimate flux-core extern spec is rejected. The local self type the check sees is always a `__FluxExternImplStruct...` wrapper, never the actual user-written self type.

**Trajectory:** Divergent against. The check is over-rejecting on a systematic, name-recognizable pattern.

**Mode:** Induction (CI is the experiment).
**Confidence:** 99% — the failure shape is uniform across 111 sites.

**Kill condition / edge:** Why does `tcx.type_of(impl_id)` return a wrapper struct? Trace the macro expansion.

---

## H₁ — Macro emits a wrapper struct; the user's `impl` is rewritten to be on the wrapper (CONFIRMED)

**Hypothesis:** The `extern_spec` macro generates:
```rust
const _: () = {
    struct __FluxExternImplStructX<...>( <generic_fields>, #self_ty );  // last field = real self_ty
    impl __FluxExternImplStructX<...> {
        fn __flux_extern_extract_impl_id() where #self_ty: #trait_ {}   // "dummy_impl"
    }
    impl #trait_ for __FluxExternImplStructX<...> { /* user methods */ } // rewritten user impl
};
```
So `impl_id` (= `item_at(0)`, the last block stmt) is the trait impl on the *wrapper*; its self type IS the wrapper struct. The user's real self type is preserved in two places: (a) the last tuple-field of the wrapper struct, (b) the where-clause of `__flux_extern_extract_impl_id`.

**Perturbation:** Read `lib/flux-attrs-impl/src/extern_spec.rs:162-200` (macro emit) and `crates/flux-driver/src/collector/extern_specs.rs:367-385` (`extract_extern_id_from_impl`).

**Evidence:**
- `extern_spec.rs:174-175`: `fields.push(parse_quote!(#self_ty))` appends the real self_ty as a struct field.
- `extern_spec.rs:178-182`: `impl ... __dummy { fn __flux_extern_extract_impl_id() where #self_ty: #trait_ {} }`.
- `extern_spec.rs:197`: `#extern_item_impl` is the user's impl, but `ExternItemImpl::to_tokens` (line 273-291) substitutes `self.dummy_ident` in place of the original self type.
- `extern_specs.rs:367-385` already extracts the trait_ref via `predicates_of(item_id.owner_id.def_id)` → `clause.as_trait_clause()` → `trait_pred.trait_ref`. The self type of that trait_ref IS the user's intended self type.

**Trajectory:** Divergent confirming. The wrapper field and the where-clause both encode the real self_ty; nothing else does.

**Mode:** Deduction (read the code).
**Confidence:** 97%.

**Edge:** Use `trait_ref.self_ty()` from the same predicate the collector already reads.

---

## H₂ — Fix: read the real self type from the dummy_impl's where-clause

**Hypothesis:** The check should compare `trait_pred.trait_ref.self_ty()` (the user's intended self type, in the local crate's param space) against `tcx.type_of(extern_impl_id).instantiate_identity()` (the extern impl's self type, in the extern crate's param space). After `check_generics` has run, type-param equality reduces to `ParamTy { index, name }` equality, so naive `==` is sound for the param case.

**Perturbation plan:**
1. Refactor `extract_extern_id_from_impl` to also return the `trait_ref` (or expose the predicate so the caller can take both `impl_id` and `self_ty()`).
2. Replace `tcx.type_of(local_id).instantiate_identity()` in `check_extern_impl_self_ty` with the trait_ref's `self_ty()`.
3. Verify the negative test still fails (`Range<usize>` vs `Range<A>` — concrete `usize` vs `ParamTy(A)` are unequal).
4. Re-run CI on flux-core (all 111 sites should pass: e.g. `impl TryFrom<i128> for isize` in user code → trait_ref.self_ty() = `isize` = extern self_ty).

**Predicted trajectory:** Divergent confirming — flux-core compiles, negative test still errors, no false positives.

**Risks to test:**
- R1: Wrapper struct's where-clause might encode predicates differently when generics are present. Need to verify `poly_trait_pred.no_bound_vars()` still works for the lifetime-generic case (`impl<'a> Iterator for &'a Range<usize>`).
- R2: ParamTy with same index but renamed (e.g. user writes `<B>` instead of `<A>`) — check_generics rejects this *only if* it checks names. Need to verify.
- R3: Concrete generic args (`Range<usize>` extern vs `Range<usize>` local) — both are `TyKind::Adt(Range, [usize])`; Adt DefIds for stdlib types are the same across crates (no rewriting). Confirmed by existing `check_generics` flow.

**Mode:** Abduction → Deduction.
**Confidence:** 80% (high on the mechanism, medium on edge cases R1/R2).

**Edge:** Implement, re-run CI, classify.

---

## Provenance

- Issue #833 opened by `nilehmann` (maintainer) on 2024-10-01, labeled `good first issue`. Asks specifically for "check that the self-type of extern specs for trait implementations matches the external definition."
- Existing `check_generics` (extern_specs.rs:~285) handles the generic-param structural check. The PR composes on top of it but introduced the regression because it ran on the wrong representation.
- No prior PRs found via `gh pr list --repo flux-rs/flux --search "extern spec self type"`.

## H₂ — Implementation result (CONFIRMED, local, 2nd push)

**Perturbation:** Refactored `extract_extern_id_from_impl` to return `(extern_impl_id, local_self_ty)`, where `local_self_ty = trait_pred.trait_ref.self_ty()`. Threaded the self_ty into `check_extern_impl_self_ty`, dropping the `tcx.type_of(local_id)` lookup that resolved to the `__FluxExternImplStruct...` wrapper.

**Result (docker, sweep-tester:latest):**
- `cargo check -p flux-driver` clean.
- `cargo xtask test extern_specs`: flux-core extern-spec collection now passes — `summary. 60 functions processed: 2 checked; 58 trusted` for flux-core, vs. 111 errors before. The remaining failure is `failed to run fixpoint: No such file or directory` (SMT binary missing in the test container, unrelated to extern-spec collection).
- All 111 `__FluxExternImplStruct...` vs `<concrete>` errors that defined H₀ are gone.

**Trajectory:** Divergent confirming for the extern-spec collection layer. CI (which has fixpoint) will close R1/R2/R3 properly.

**Mode:** Induction (local run).
**Confidence:** 92% (local validation reached the next failure boundary, leaving CI to verify the negative test still fails and the generic-param cases survive).

## Graph state

| Node | Status | Trajectory | Mode |
|------|--------|------------|------|
| H₀ | killed | divergent-against | induction |
| H₁ | confirmed | divergent-confirming | deduction |
| H₂ | implemented-locally | divergent-confirming | induction |

## Frontier edges

- E1: Push to PR; let CI run on Linux with full toolchain (fixpoint available). Predicted: tests + vtock + lean-demo all pass.
- E2: Risk R1 (generic lifetimes): CI's `vtock` exercises lifetime-generic extern specs — if it passes, R1 is closed.
- E3: Risk R2 (param renaming): negative test `mismatched_impl_self_ty.rs` exercises this — if it still errors on CI, R2 is closed.

## Pruning log

- H₀ killed by H₂: the local self type from `tcx.type_of` is the wrapper, not the user's intent. Replaced by reading `trait_ref.self_ty()` from the dummy_impl's predicate.

## H₃ — Test author error (CONFIRMED, 2026-05-19 reinvestigate)

**Observation:** After H₂ push, CI shows only one failing job (`tests`), and only one failing test (`neg/extern_specs/mismatched_impl_self_ty.rs`). The flux-core regression is fully gone — H₂ confirmed at scale.

**Hypothesis:** The test file uses `#[flux::extern_spec(std::ops)]` — the raw post-macro-expansion attribute — instead of the proc-macro form `#[extern_spec(std::ops)]` from `flux_attrs`. Without the macro expansion, the const-block / dummy-struct / `__flux_extern_extract_impl_id` fn that `extract_extern_id_from_impl` requires never gets generated, so the new code path silently falls back to a different error.

**Perturbation (local docker):** Ran the single test against the latest driver.

**Result:**
```
not found errors (from test file): "invalid extern spec for trait impl"
actual errors emitted:            "invalid extern spec for implementation [E0999]"
```

The actual error is `driver_mismatched_generics` (def_descr=implementation), not the new `MismatchedImplSelfTy`. So with no generic params declared, `check_generics` rejects the impl first because the external `impl<A: Step> Iterator for Range<A>` has one generic param and the test impl has zero.

**Mode:** Induction (local repro).
**Confidence:** 99%.

## H₄ — Test rewrite mirrors issue example (CONFIRMED)

**Perturbation:** Rewrote `mismatched_impl_self_ty.rs` to use the proc-macro form and declare `<A: Step>` so generic counts match. This is exactly the example from issue #833.

```rust
#![feature(step_trait)]
use std::iter::Step;
use flux_attrs::extern_spec;

#[extern_spec(std::ops)]
impl<A: Step> Iterator for Range<usize> {} //~ ERROR invalid extern spec for trait impl
```

**Result (docker, sweep-tester:latest):**
```
test [compile-fail] neg/extern_specs/mismatched_impl_self_ty.rs ... ok
test result: ok. 1 passed; 0 failed
```

**Trajectory:** Divergent confirming. The `MismatchedImplSelfTy` diagnostic fires exactly as designed.

**Mode:** Induction.
**Confidence:** 95% (local container lacks the fixpoint binary so other extern_specs tests can't be cross-checked; CI will).

## Updated graph state

| Node | Status | Trajectory | Mode |
|------|--------|------------|------|
| H₀ | killed | divergent-against | induction |
| H₁ | confirmed | divergent-confirming | deduction |
| H₂ | confirmed-by-CI | divergent-confirming | induction |
| H₃ | confirmed | divergent | induction |
| H₄ | confirmed | divergent-confirming | induction |

## Frontier edges

- E4: CI on the new commit — predicted: all jobs green (the only failing test is now the rewritten one, and it asserts a `//~ ERROR` annotation that the driver now emits).

---

## H₅ — Reinvestigate (2026-05-19): error span is macro-generated, compiletest annotation can't match

**Context:** After commits 0a91dac (read self_ty from trait_ref) and 3afe048 (test in proc-macro form), only one test fails on CI: `neg/extern_specs/mismatched_impl_self_ty.rs`. 432 pass, 1 fails. The check fires (no over-rejection), but compiletest reports the test failed.

**Hypothesis:** The diagnostic's primary span is `local_impl.self_ty.span`, where `local_impl` is the macro-generated `__FluxExternImplStruct` wrapper. That self_ty span is synthesized by the `extern_spec` proc-macro and doesn't correspond to the user's source line. compiletest's `//~ ERROR ...` annotation must match the primary span's line; a macro-internal span never matches.

**Perturbation:** Change the span source from `local_impl.self_ty.span` (dummy wrapper) to `tcx.def_span(local_impl_id)` (user's actual impl block). Drop the now-unused `dummy_impl` plumbing through `check_extern_impl_self_ty`.

**Trajectory:** Divergent (predicted). Only failure mode the symptom is consistent with — error is emitted (check fires) but compiletest doesn't recognize it as matching the annotation.

**Mode:** Deduction (read the code: dummy wrapper's self_ty is `__FluxExternImplStruct...`, span is macro-generated).
**Confidence:** 90%. Local CI run not possible (sweep-tester missing `fixpoint` binary); compile verified, CI is the remaining check.

**Kill condition:** if CI still fails on this test after the span change, the actual emitted error has a different message OR no error fires at all → re-investigate.
