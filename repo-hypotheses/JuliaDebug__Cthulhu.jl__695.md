# JuliaDebug/Cthulhu.jl#695 — Cthulhu should display ambiguous method matches

## Issue

Keno reports that when inference encounters an ambiguous method match
(multiple methods match the signature with no most-specific winner), Cthulhu
shows the resolved callsite without any indication that the dispatch was
ambiguous. The example: a single-field mutable struct whose `convert`
overload (`::Type{V}, ::Any`) collides with the universal
`convert(::Type{T}, x::T) where T` produces a `!n` (not nothrow) effect that
the user had to chase manually via `methods_including_ambiguous` at the REPL.

> "I feel like this should have been annotated in the callsite display."

## Hypothesis graph

### H₀ — Cthulhu drops the `ambig` bit from `MethodMatchInfo`

**Perturbation.** Read `src/compiler/reflection.jl:174-182` (the
`MethodMatchInfo` branch of `process_info`). The branch iterates
`info.edges` to build `EdgeCallInfo`s, never reading
`info.results.ambig`.

**Trajectory.** Divergent — confirmed by inspection. Julia's
`MethodLookupResult` carries an `ambig::Bool` that is true whenever any
match in the result is shadowed by an ambiguity. Cthulhu has access to
it (`info.results.ambig`) and discards it.

**Edge.** Wrap the resulting `CallInfo`s in a marker so downstream display
can annotate them.

### H₁ — A new `AmbiguousCallInfo <: WrappedCallInfo` is the right shape

**Perturbation.** Survey the existing display vocabulary in
`src/compiler/callsite.jl`. `LimitedCallInfo` already uses the
`WrappedCallInfo` pattern with a `_wrapped_callinfo(limiter, …)` method that
renders as `< limited >`. Other markers (`< pure >`, `< constprop >`,
`runtime < … >`, `invoke < … >`) all use the same chevron framing.

**Trajectory.** Convergent — the existing convention dictates the shape.
Following "Go with the flow," mirror `LimitedCallInfo`: a new
`AmbiguousCallInfo` wrapping a `CallInfo`, rendered as `< ambiguous >`.

### H₂ — Top-level callsite for the issue's exact reproducer is one frame deeper

**Perturbation.** Replicate the issue's reproducer (mutable struct H with
`x::V`, ambiguous `convert(::Type{V}, ::Any)`) and call
`find_callsites_by_ftt(makeH, Tuple{Any}; optimize=false)`. Then descend
into the H constructor.

**Trajectory.** Oscillatory — at the `makeH` level Cthulhu shows a single
`MultiCallInfo` for `H(::Any)`; the ambiguous `convert` lives one frame
down inside the auto-generated constructor. At `H(::Any)` level the wrapped
`AmbiguousCallInfo` appears directly. The test reproducer needs to call
`convert` from the top frame (or descend a level) for the test to be
direct and stable.

**Edge.** Refactor the test to call `convert(V, x)` directly from a top-level
function (`callconvert`) so the AmbiguousCallInfo appears in the first
layer of callsites. Keeps the test small and independent of constructor
codegen details.

### H₃ — `info.results` is always present on `MethodMatchInfo`

**Perturbation.** Read Julia's `Core.Compiler.MethodMatchInfo` definition
across supported versions. It has been `(results, mt, atype, edges)` for
many releases. Still, guarding with `isdefined(info, :results)` is cheap
and future-proofs against compiler-internal field shuffles that Cthulhu
has historically had to chase (see e.g. commits adjusting
`VirtualMethodMatchInfo`).

**Trajectory.** Convergent — guarded read is the right defensive default
for compiler-internal types Cthulhu doesn't own.

## Fix

`src/compiler/reflection.jl`

```julia
if isa(info, MethodMatchInfo)
    ambig = isdefined(info, :results) && getfield(info.results, :ambig) === true
    return CallInfo[let
        ci = if edge === nothing
            RTCallInfo(unwrapconst(argtypes[1]), argtypes[2:end], rt, exct)
        else
            effects = @something(effects, get_effects(edge))
            EdgeCallInfo(edge, rt, effects, exct)
        end
        ambig ? AmbiguousCallInfo(ci) : ci
    end for edge in info.edges if edge !== nothing]
end
```

`src/compiler/callsite.jl` — add the wrapper next to `LimitedCallInfo`:

```julia
struct AmbiguousCallInfo <: WrappedCallInfo
    wrapped::CallInfo
end
```

…and its renderer alongside the existing `_wrapped_callinfo` for
`LimitedCallInfo`:

```julia
_wrapped_callinfo(limiter, ::AmbiguousCallInfo) = print(limiter, "ambiguous")
```

Also propagate the marker through `MultiCallInfo` so a union-split that
lands on multiple ambiguous arms still surfaces the warning at the
parent's `call …` line:

```julia
function print_callsite_info(limiter::IO, info::Union{MultiCallInfo, FailedCallInfo, GeneratedCallInfo})
    if isa(info, MultiCallInfo) && any(ci -> isa(ci, AmbiguousCallInfo), info.callinfos)
        printstyled(limiter, "ambiguous "; color=Base.warn_color())
    end
    print(limiter, "call ")
    show_callinfo(limiter, info)
end
```

## Attestation

- **Fail-on-master.** With the production change reverted, the new test's
  first assertion (`!isempty(ambig_csis)`) fails — `AmbiguousCallInfo`
  never gets attached.
- **Pass-on-fix.** Full ambiguity test passes (3/3 assertions in the
  testset) on the branch.

## Reasoning mode

| Claim | Mode | Confidence |
|-------|------|-----------|
| `MethodMatchInfo.results.ambig` exists and is the right signal | Deduction (read Julia source) | 95% |
| `AmbiguousCallInfo <: WrappedCallInfo` mirrors the codebase convention | Deduction (read existing wrappers) | 95% |
| Test reproducer needs `convert` at top level, not nested in `H` ctor | Induction (ran the perturbation, observed empty result for makeH-level callsites, non-empty for direct convert) | 95% |
| MultiCallInfo "ambiguous " prefix is useful (covers union-split cases) | Abduction | 65% — not exercised by the test, but symmetrical with the wrapped renderer |
