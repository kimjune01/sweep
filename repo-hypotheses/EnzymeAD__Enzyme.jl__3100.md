# EnzymeAD/Enzyme.jl#3100 — Strange EnzymeRuntimeActivityError on 1.12

**Status**: halted at Phase 1 (no perturbation surface).

## H₀ (untested)
Julia 1.12 changed lowering for a construct that Enzyme's activity analyzer relied on; the activity propagation through graded-tensor inner field loads (LLVM `load ptr addrspace(10), ptr addrspace(11) %15`) misclassifies a const value as needing differentiation. Reporter confirmed the same test passes on Julia 1.10.

## Why no fan-out

- Worktree not cached (`sweep project-info` returns `worktree_exists: false`).
- Reproducer requires Julia 1.12 + TensorKit + MatrixAlgebraKit + EnzymeTestUtils. Building the Enzyme.jl LLVM bindings in `sweep-tester:latest` is hours of cold-cache cost before the first perturbation.
- Failure is in the compiler's static activity analysis (downstream of Julia IR changes between 1.10 → 1.12). Static reading alone yields abductions only — no induction is possible without running the JIT pipeline against a 1.12 build.
- Rules: "Perturbation access is required. If you can't poke the system, you can't investigate it. Say so and stop."

## Candidate edges (for whoever picks this up with a working Julia 1.12 setup)

1. **Bisect Julia 1.10..1.12** on the minimal eigh_full reproducer to identify the lowering change.
2. **Bisect Enzyme.jl main** on Julia 1.12 against the reproducer to identify whether any recent activity-analyzer change is implicated.
3. Examine the type `TensorMap{Float64, GradedSpace{ProductSector{(A4Irrep, Z4Element{2})}, NTuple{16, Int64}}, 1, 1, Vector{Float64}}` — the "Unknown object of type Any" in the error suggests an `Any`-typed field in the sector dictionary that activity inference can't see through. Compare 1.10 vs 1.12 typed-IR for this object's field access.
4. The `!dbg !8` load at `addrspace(11)` from `addrspace(10)` is a `getfield` on a heap-allocated Julia object; check whether Julia 1.12's GC-rooting changes added a load Enzyme's analyzer doesn't recognize.

## Frontier
All edges above require Julia 1.12 + a built Enzyme.jl. Reopen if the worktree is cached and that environment is available; otherwise route to human.

## Provenance
- Pack: `/var/folders/26/.../inv-ctx-triage-2026-05-18T23_17Z-EnzymeAD-Enzyme.jl-3100.md`
- Reporter: kshyatt; followup confirmed 1.10 works.
- No related open PRs.
- No prior PRs by kimjune01 on this repo.
