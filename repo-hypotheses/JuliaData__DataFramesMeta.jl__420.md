# JuliaData/DataFramesMeta.jl#420 — `@subset(df, true|false)` literal support

**Target:** PR #420 (open, CI green) fixing issue #259 (open since 2021-06-20).
**Status at investigation start:** PR shipped, awaiting maintainer review. Investigation is post-ship risk assessment, not pre-ship diagnosis.

## H₀: The fix as written closes #259 cleanly and will be accepted as-is

- **Null:** A maintainer will request redesign or close without merge.
- **Perturbation:** Read the PR diff, issue thread, CI rollup, and the surrounding `fun_to_vec` dispatch chain.
- **Trajectory:** **Oscillatory.** CI is green across Julia 1.10/1.12 × ubuntu/macOS/windows and the test set exercises the documented cases. But issue #259 has a 2024 collaborator comment (`pdeffebach`, the issue opener) that explicitly says the design *"is actually kind of complicated"* and floats two alternatives the PR ignores: (a) an `allow_literals` keyword scoped to `@subset`/`@orderby`, or (b) requiring `^(true)` escape. The PR neither acknowledges nor refutes that comment.
- **Shape classification:** Oscillatory — green CI says "works"; the unaddressed maintainer comment says "wrong shape." Split.
- **Kill condition:** A maintainer review citing the 2024 comment would kill H₀.
- **Edge → H₁, H₂.**

## H₁: The catch-all scope (any `no_dest=true` macro) matches what the maintainer wanted

- **Null:** The scope is wider than the maintainer asked for; reviewer pushback follows.
- **Perturbation:** Grep `no_dest=true` call sites in `src/macros.jl`.
- **Evidence:**
  - Macros that now accept literals: `@subset`, `@subset!`, `@rsubset`, `@rsubset!`, `@with`, `@distinct`, `@distinct!`, `@rdistinct`, `@rdistinct!`.
  - Maintainer's 2024 comment named only `@subset` and `@orderby` as candidates ("only for `@subset` and `@orderby`").
  - `@orderby` does not appear in this repo's source (only `@n`, possibly renamed); the maintainer's comment may predate or postdate a rename. Not load-bearing either way — the scoping concern stands.
- **Trajectory:** **Divergent against H₁.** The PR enables literals in `@with` and `@distinct` family without justification. `@with(df, true)` previously errored; it now returns `ByRow(Returns(true))` evaluated as a length-`nrow(df)` vector, which is a behavior change `@with` users didn't ask for.
- **Shape classification:** Divergent against. The scope mismatch is real.
- **Reasoning mode:** Deduction (read code, traced call sites). Confidence ~95%.
- **Kill condition:** N/A — this is confirmed against.
- **Edge → H₃ (mitigation): can the dispatch be narrowed without rewriting?**

## H₂: The maintainer's `^(true)` escape proposal is dead

- **Null:** It is alive — they will ask for it.
- **Perturbation:** Re-read the 2024 comment ("I don't know maybe we want `^(true)` instead"). Search for `^(` usage in DataFramesMeta source.
- **Evidence:** The 2024 comment is contemplative ("I don't know maybe"), not a decision. Two years passed without action. `^(...)` is already used in DataFramesMeta as an "escape this expression" operator, which makes it a plausible-but-not-mandatory candidate. The opener never returned to push it.
- **Trajectory:** **Convergent (weakly).** The proposal is likely dormant rather than dead — a reviewer reading the issue *cold* will see it and ask why the PR took a different path.
- **Shape classification:** Convergent — partial confirmation that `^(true)` is not the actively preferred mechanism, but the dormant proposal is the most likely reviewer challenge.
- **Reasoning mode:** Abduction from issue history. Confidence ~70%.
- **Edge → H₄: PR description should preemptively address the `^(true)` and `allow_literals` alternatives.**

## H₃: Narrowing the dispatch to `@subset`/`@rsubset` only is cheap

- **Null:** It requires structural surgery.
- **Perturbation:** Read `fun_to_vec` dispatch and `subset_helper`/`with_helper`/`distinct_helper`.
- **Evidence:** All `no_dest=true` callers pass through the same `fun_to_vec` entry. The current catch-all triggers on *any* literal regardless of caller. To scope to `@subset` only, the caller would need to pass a discriminator (e.g., a new `allow_literals::Bool` keyword) and the catch-all would gate on it. This is the *exact mechanism the maintainer proposed in 2024.*
- **Trajectory:** **Divergent toward maintainer's preference.** A ~10-line change to `fun_to_vec` signature plus passing `allow_literals=true` from `subset_helper`/`rsubset_helper`/`subset!_helper`/`rsubset!_helper` would land the fix with the exact shape the maintainer asked for.
- **Shape classification:** Divergent — clear edge.
- **Reasoning mode:** Deduction. Confidence ~90%.
- **Edge → frontier: implement `allow_literals` keyword if the maintainer pushes back, but don't preemptively rewrite; current PR may still be accepted.**

## H₄: A preemptive comment on the PR matching the maintainer's vocabulary lowers rejection risk

- **Null:** Silence is fine; reviewer will engage on technical merits and either accept or request changes.
- **Perturbation:** Memory says "Maintainer self-PR halt" — not applicable here (opener is collaborator pdeffebach, PR author is `kimjune01`). Memory also says "Signal → artifact" and "Verify quantitative claims."
- **Trajectory:** **Convergent.** A short PR comment naming the 2024 alternatives ("considered `allow_literals` keyword and `^(true)`; chose catch-all via `no_dest` because the same dispatch table already partitions subset-family from select-family — happy to switch to `allow_literals` if preferred") shifts the burden from "did the author read the issue?" to "which design do you prefer?"
- **Shape classification:** Convergent.
- **Reasoning mode:** Abduction from contributor etiquette. Confidence ~75%.
- **Edge → frontier: post the comment OR wait for review. Recommend: wait one review cycle; if any redesign push, switch to `allow_literals` immediately rather than defending the catch-all.**

## Graph state

| Node | Status   | Mode      | Shape          | Confidence |
|------|----------|-----------|----------------|------------|
| H₀   | refined  | deduction | oscillatory    | —          |
| H₁   | confirmed against (scope mismatch is real) | deduction | divergent | 95% |
| H₂   | partial (proposal dormant, not dead) | abduction | convergent | 70% |
| H₃   | confirmed (narrowing is cheap, ~10 lines) | deduction | divergent | 90% |
| H₄   | open (action not yet taken) | abduction | convergent | 75% |

## Frontier edges

1. **Wait for first review.** If reviewer asks for `allow_literals` scoping, the patch from H₃ is ~10 lines and ready. Don't preemptively rewrite — the catch-all may merge as-is.
2. **Do not duplicate.** No existing PR addresses #259 (checked via PR list earlier in this codebase's lineage). #420 is the only candidate.
3. **`@with(df, true)` behavior change.** New behavior returns a length-`nrow(df)` constant vector. Not tested in the PR. If the reviewer cares, this needs an explicit test or a narrower scope.

## Causal chain

H₀ (PR accepted as-is) is oscillatory: the test/CI evidence converges, but the design evidence (maintainer's 2024 comment) diverges. H₁ confirms the divergence is real — the scope is wider than asked. H₃ shows the fix is cheap. The recommended state is: ship the current PR, hold the H₃ patch in reserve, and respond to review with the `allow_literals` rewrite if asked.

## Pruning log

- *Killed:* "Maintainer self-PR halt" rule (memory). Doesn't apply — opener and PR author are different identities.
- *Killed:* "Fix is wrong / CI is masking it." CI is genuinely green and the test cases match the issue's request. The risk is design, not correctness.
- *Refined:* H₀ split into H₁ (scope), H₂ (`^(true)`), H₃ (mitigation), H₄ (preemptive comment).

## Provenance

- PR #420 commits: `bb93457` (initial fix), `36b06d7` (return `AbstractVector` via `ByRow(Returns(...))` — the current shape).
- Issue #259 opener: pdeffebach (collaborator); first comment 2021-09-19 noting `Returns` is in Julia 1.7; second comment 2024-03-01 raising the scoping concern.
- Existing mechanism overlooked? No — `fun_to_vec` had no dispatch for literals; the PR adds the first. The maintainer's preferred shape (`allow_literals` keyword) was never built either.

## Reframe check

Investigation does not reframe the original question. The fix addresses #259's behavior. The open question is design alignment, not correctness.

## Halt

Frontier is open but action is deferred to first review cycle. No further perturbation produces decisive evidence without a maintainer signal. Phase 8 (ship) is already done; the meaningful next event is external (reviewer response).
