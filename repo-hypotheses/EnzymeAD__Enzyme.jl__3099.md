# EnzymeAD/Enzyme.jl#3099 — FunctionWrappers: "Call parameter type does not match function signature!"

**Status**: halted at Phase 1 (no perturbation surface + maintainer self-report).

## H₀ (untested)
Enzyme's preprocessing of the `jlcapi_CallWrapper_<N>` shim that FunctionWrappers.jl emits for `FunctionWrapper{Nothing, Tuple{Vector,Vector,Vector}}` doesn't agree with the callsite types after Enzyme's type-analysis decorates the arguments. The error message:

```
Call parameter type does not match function signature!
  %"new::Array" = call ... ptr addrspace(10) @julia.gc_alloc_obj(...)
  ptr  call void @jlcapi_CallWrapper_3136(ptr addrspace(10) ..., ptr addrspace(10) ..., ptr addrspace(10) %"p::Array") ...
```

shows the call passes three `ptr addrspace(10)` operands while the callee declaration has been rewritten (or never updated) to a plain `ptr` parameter — the addrspace(10) → ptr mismatch the LLVM verifier rejects.

This is the same family as several known Enzyme + ccall / cfunction wrapper issues: the body of a Julia-emitted C-callable trampoline isn't visible to Enzyme through normal IR walking, so when Enzyme cloning or type-erasure rewrites the wrapper signature it diverges from the caller.

## Why no fan-out

- `sweep project-info` returns `worktree_exists: false` — no cached Enzyme.jl checkout.
- Reproducing requires Julia + a built Enzyme.jl + FunctionWrappers; the LLVM-bound Enzyme build is hours of cold-cache cost inside `sweep-tester:latest`.
- The failure is at the LLVM IR level inside Enzyme's preprocess pipeline; static reading of `.jl` source alone produces abductions, no induction.
- **Maintainer self-report.** Reporter is `wsmoses`, the Enzyme.jl lead. Per `[[feedback_maintainer_self_pr]]`, halt before investigating: the maintainer almost certainly already has the IR dump in front of him and a faster mental model than any external contributor can build.
- Per investigate.md rule: "Perturbation access is required. If you can't poke the system, you can't investigate it. Say so and stop."

## Adjacent work to watch (don't duplicate)

- **#3112** — *Hide deferred_codegen ccall body behind overlay table* (gbaraldi). Touches exactly the ccall/overlay path that `jlcapi_CallWrapper_*` rides on. Plausibly resolves or interacts with #3099 once it lands. Track its status before any external fix attempt.

## Candidate edges (for whoever picks this up with a working Enzyme.jl build)

1. Capture the unoptimized LLVM module just before Enzyme's verifier fails; diff the `jlcapi_CallWrapper_3136` declaration vs its callsite to see which side has the wrong type.
2. Check whether Enzyme's `julia_activity.cpp` / `EnzymeLogic.cpp` type-rewriter strips `addrspace(10)` from declarations of imported `jlcapi_*` symbols when the function body isn't in the module.
3. Bisect Enzyme.jl `main` around the most recent type-analysis changes for FunctionWrappers / ccall trampolines.
4. Apply #3112 locally and re-run the reproducer — if it already fixes #3099, file as a duplicate-resolved-by note.

## Frontier

All edges require a working Julia + Enzyme.jl build. Reopen if the worktree is cached AND #3112 hasn't already absorbed the failure mode.

## Provenance

- Pack: `/var/folders/26/.../inv-ctx-triage-2026-05-18T23_17Z-EnzymeAD-Enzyme.jl-3099.md`
- Reporter: wsmoses (Enzyme.jl maintainer) — maintainer self-report halt.
- Related open PR: #3112 by gbaraldi on the deferred_codegen ccall path.
- No prior PRs by kimjune01 on this repo.
- Sister halt: `[[EnzymeAD__Enzyme.jl__3100]]` — same repo, same reason class (no worktree, LLVM-pipeline failure).
