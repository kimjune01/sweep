# JuliaDebug/Cthulhu.jl#696 — unhandled `VirtualMethodMatchInfo`

**Status**: diagnosis converged, fix verified fail-on-master / pass-on-fix.

## H₀ — observation

Issue reports: `@descend p * x` in VSCode raises
`unhandled Compiler.CallInfo of type Compiler.VirtualMethodMatchInfo`
from `Cthulhu/src/compiler/reflection.jl:253` (the `error(...)` in
`process_info`'s fall-through `else` branch). Non-VSCode terminal works fine.
Julia 1.12.5.

## H₁ — `VirtualMethodMatchInfo` is a CallInfo type that `process_info` lacks a branch for

**Perturbation**: read `process_info` (src/compiler/reflection.jl:156-255) and
list every `CC.*Info` it handles. Cross-reference against
`JuliaLang/julia:Compiler/src/stmtinfo.jl`.

**Trajectory**: divergent-confirm. `VirtualMethodMatchInfo` is defined in
Julia 1.12's `Compiler/src/stmtinfo.jl:467-471`:

```julia
struct VirtualMethodMatchInfo <: CallInfo
    info::Union{MethodMatchInfo,UnionSplitInfo,InvokeCallInfo}
end
```

It's a thin wrapper. `process_info` has branches for `MethodMatchInfo`,
`UnionSplitInfo`, `InvokeCallInfo`, etc., but no branch for the wrapper, so
it falls through to `error(...)`.

## H₂ — why "VSCode-only"?

**Perturbation**: trace the descend path that VSCode exercises vs the terminal
path.

**Trajectory**: convergent. `cthulhu_typed` (src/compiler/codeview.jl:96) calls
`add_callsites!` (codeview.jl:251) only when `diagnostics_vscode ||
inlay_types_vscode` is on. `add_callsites!` recursively descends into every
callsite's CI to gather inlay-hint / diagnostic data, calling
`find_callsites` → `process_info` on each. The terminal path lists callsites
at the current frame and stops. So VSCode hits virtual-dispatch sites the
terminal path never reaches — hence "VSCode-only". The bug is in
`process_info`, not in the VSCode integration.

## H₃ — what produces `VirtualMethodMatchInfo` in inferred IR?

**Perturbation**: grep Julia compiler for `VirtualMethodMatchInfo(`
constructors.

**Trajectory**: divergent. Two sites in `Compiler/src/tfuncs.jl`:
`applicable_tfunc` (line 3237) and `_hasmethod_tfunc` (line 3278). Both produce
it for non-trivial `applicable(f, args...)` and `Core._hasmethod(...)` calls
where rt resolves to `Const(true)`/`Const(false)`.

**Minimal repro** (no FFTA needed):

```julia
foo(x) = applicable(sin, x)
find_callsites(provider, lookup(provider, ci, false), ci)
# → ERROR: unhandled Compiler.CallInfo of type Compiler.VirtualMethodMatchInfo
```

Confirmed locally in `sweep-tester:latest` (Julia 1.12.6).

## H₄ — fix shape

**Abduction**: mirror the existing `ModifyOpInfo` unwrap pattern at the top of
`process_info`. The wrapped `info.info` is already in the union the function
handles (`MethodMatchInfo`/`UnionSplitInfo`/`InvokeCallInfo`).

**Perturbation**: add

```julia
if isdefined(CC, :VirtualMethodMatchInfo) && isa(info, CC.VirtualMethodMatchInfo)
    info = info.info
end
```

after the `ModifyOpInfo` unwrap (src/compiler/reflection.jl:161-164).
`isdefined` guard for safety even though Cthulhu's `Project.toml` already pins
`julia = "1.12"` — costs nothing and survives any back-port.

**Regression test** (test_Cthulhu.jl):

```julia
f696(x) = applicable(sin, x)
@testset "issue #696" begin
    @test_nowarn find_callsites_by_ftt(f696, Tuple{Int}; optimize=false)
end
```

**Verification** (docker sweep-tester:latest, Julia 1.12.6):
- master + test → `unhandled Compiler.CallInfo of type Compiler.VirtualMethodMatchInfo` (matches reporter)
- fix + test → 0 callsites returned, no error

## Reasoning mode

- H₀: induction (read the issue).
- H₁, H₃: deduction (read Julia + Cthulhu source). Confidence 99%.
- H₂: deduction (traced the VSCode codepath). Confidence 95%.
- H₄: deduction (the wrapper struct exposes `.info` of exactly the right
  union). Verified by induction (docker run). Confidence 99%.

## Frontier

Closed. The fix unwraps the wrapper into a type the existing switch already
handles. No oscillatory residue.
