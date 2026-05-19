# triton-lang/triton#10278 — Hypothesis Graph

PR: Fix WarpSpecialization heuristic bugs and style inconsistencies
Branch: `fix-warp-specialization-heuristics` (kimjune01 fork)
Origin issue: triton-lang/triton#9853 (oonyshch, 2026-03-25)
Status: **CI failing — compile error**

## H₀: PR is correct as written and CI failure is unrelated
- Null: PR contains a defect.
- Perturbation: pulled CI logs for run 25613294870.
- Trajectory: **divergent against**. All 6 platform jobs fail with the same compile error:
  `PartitionScheduling.cpp:1154:29: error: no member named 'emplace' in 'llvm::DenseMap<Node*, Node*>'`.
- Kill condition: identical failure across macOS / nvidia-a100 / amd-gfx90a/942/950 ⇒ deterministic compile bug from the PR diff, not flaky infra.
- Edge → H₁.

## H₁: `std::map`→`DenseMap` migration in `duplicateCheapOps` missed an API mismatch
- Null: all `std::map` member calls are also valid `DenseMap` calls.
- Perturbation: read line 1154 on PR branch; `parentMap.emplace(child, node)` is still present after the type was changed at line 1137.
- Trajectory: **divergent confirming**. `llvm::DenseMap` exposes `try_emplace` and `insert`, but no `emplace`. `std::map::emplace` has no direct DenseMap analogue with the same name. The PR converted only the declaration site and the `.find()` lookup; the insertion site was overlooked.
- Reasoning mode: deduction (code trace) — confidence 98%.
- Edge → H₂ (fix shape).

## H₂: minimal fix is `emplace` → `try_emplace`
- Null: a different replacement (`insert({k,v})`, `operator[]`) is required.
- Perturbation: review LLVM DenseMap.h API. `try_emplace(key, args...)` constructs in place and is a 1:1 semantic match for `std::map::emplace(key, value)` when the key is absent (both no-op if key already exists). `operator[] = v` would overwrite, which differs from `emplace` semantics — but in this code the surrounding guard `if (!seen.contains(node))` already enforces single-visit, so behavior is observationally identical. Prefer `try_emplace` to preserve original intent and pass review.
- Trajectory: **convergent**. One-line change at 1154.
- Reasoning mode: deduction — confidence 95%.

## H₃: the `if_op_result_token` heuristic `return false` fix is semantically correct
- Null: the empty body was intentional (deliberate fallthrough).
- Perturbation: cross-check sibling heuristics in the same array (`for_op_iter_arg_token`, `sfu_consumer`). All use `if (!predicate) return false;` as guard idiom. Reporter (oonyshch in #9853) explicitly identified the empty body as a missing `return false`. Comment text `// skip if not from an MMA` matches sibling comments where `return false` follows.
- Trajectory: **convergent**. Idiom-matching + reporter intent + comment text agree.
- Confidence 90% (abduction validated by three independent signals).

## H₄ (frontier, not yet tested): with the compile fix, does the `return false` change any lit-test output?
- Predicted trajectory: convergent (no behavioral regression). The heuristic now correctly rejects non-MMA edges instead of falling through into the next predicate, which itself returns false for non-`isIfResult` cases. The combined effect is the same on edges where `!isMMA(from) && !isIfResult(to)`. Behavioral divergence only on edges where `!isMMA(from) && isIfResult(to) && isa<AsyncTokenType>(to)`: old code returns true, new code returns false. That's the actual semantic change — calling it a "bug fix" is correct iff such edges should not be co-partitioned with the if-result's MMA producer (since there is no MMA producer). The reporter and idiom both agree this is the intended semantics.
- Verification path: CI lit tests on the fixed branch.

## Graph state

| Node | Status | Shape | Mode |
|------|--------|-------|------|
| H₀ | killed | divergent | induction (CI log) |
| H₁ | confirmed | divergent | deduction |
| H₂ | confirmed | convergent | deduction |
| H₃ | confirmed | convergent | abduction + corroboration |
| H₄ | confirmed | convergent | induction (CI 2026-05-18, 10/10 green) |

## Fix applied

`lib/Dialect/TritonGPU/Transforms/WarpSpecialization/PartitionScheduling.cpp:1154`
  `parentMap.emplace(child, node);` → `parentMap.try_emplace(child, node);`

## Pruning log
- H₀ killed by CI logs (deterministic same-line compile failure across all platforms).

## Next steps
- Push fix commit to `fix-warp-specialization-heuristics`. **Done** — f0a6d85.
- Watch CI; if green, H₄ resolves convergent and PR is shippable. **Done** — 10/10 SUCCESS on 2026-05-18 (a100, h100, gb200, gfx90a, gfx942, gfx950, proton-amd, macos, pre-commit, runner-preparation).
- PR state: MERGEABLE, REVIEW_REQUIRED. Awaiting maintainer review; no further substrate action.

## Halt
Frontier closed; all nodes classified. CI confirms behavioral fix is regression-free across all hardware lanes. Standalone halt — no action open.
