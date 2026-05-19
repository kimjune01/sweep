# JuliaDebug/Cthulhu.jl#694 — Missing call sites

## Issue
`@descend` on `FFTA.fft!` lists `fft_dft!`, `fft_pow2_radix4!`, `fft_pow3!`, `throw_boundserror`, `ArgumentError`, but silently drops the `fft_composite!` invoke even after toggling `[h]ide-type-stable` off.

## H₀ (observation)

**Hypothesis**: a specific `:invoke` statement in the optimized IR is being filtered out by `find_callsites` while peer `:invoke`s for `fft_dft!`/`fft_pow3!`/etc. pass through.

**Perturbation**: in-container, call `find_callsites` on the same `fft!` MethodInstance and dump the raw stmts + their `result.infos[id]` for any statement mentioning `composite` or `bluestein`.

**Trajectory**: divergent. Statement `#3` is `Expr(:invoke, CodeInstance for fft_composite!, ...)` whose `result.infos[3]` is `CthulhuCallInfo(... MethodMatchInfo(... edges = Union{Nothing, CodeInstance}[nothing] ...))`. Peer invokes for the other algorithms have non-`nothing` edges.

**Kill**: H₀ confirmed. Single-edge `MethodMatchInfo` with `edges == [nothing]` is the differentiator. (mode: induction, confidence 95%)

## H₁ (mechanism)

**Hypothesis**: `process_info` for `MethodMatchInfo` filters out `nothing` edges via `for edge in info.edges if edge !== nothing`, returning an empty `CallInfo[]`; `find_callsites` then hits `isempty(callinfos) && continue`, skipping the statement entirely — even though the `:invoke` Expr carries a perfectly good `CodeInstance` in `args[1]` that the head-dispatch fallback (line 79) would happily turn into an `EdgeCallInfo`.

**Perturbation**: read `src/compiler/reflection.jl:62-99`. Trace control flow when `MethodMatchInfo.edges == [nothing]`.

**Trajectory**: divergent — code path is dead simple. The `MethodMatchInfo` branch (lines 174-182) emits an empty vector because the only edge is `nothing`. Line 63 short-circuits with `continue`, jumping past the head-dispatch fallback that would have caught the `:invoke`. (mode: deduction, confidence 99%)

**Provenance**: the `for ... if edge !== nothing` filter has been in `process_info` since the `MethodMatchInfo`-aware refactor; combined with `is_call_expr` returning `true` for optimized `:invoke`s, this race between the two enumeration paths existed silently for any `MethodMatchInfo` whose only edge slot is `nothing`. Recursive / mutually-recursive / forward-declared functions appear to be the production source — the compiler emits a `MethodMatchInfo` whose `edges` slot for the self/forward reference is left `nothing` while the `:invoke` carries the resolved `CodeInstance`.

The unrelated open branch `fix/virtualmethodmatchinfo-696` addresses a *different* missing-callsite class (a brand-new wrapper info type), not this one. This is a separate bug.

## Reframe check
The original H₀ ("a callsite is dropped") survives — no broader reframing. The kill condition cleanly identifies the dropped path; the fix is a one-liner.

## Fix

`src/compiler/reflection.jl:62`: don't `continue` when `process_info` returns empty. Leave `callsite = nothing` and let the head-based fallback at line 75 take over — for `:invoke` it constructs `EdgeCallInfo(args[1]::CodeInstance, rt, effects)` from the Expr directly, which is in fact the *best* representation available (we have a resolved `CodeInstance`, not a runtime lookup).

```diff
-                callinfos = process_info(provider, result, info, argtypes, rt, exct, effects)
-                isempty(callinfos) && continue
-                callsite = let
-                    ...
-                end
+                callinfos = process_info(provider, result, info, argtypes, rt, exct, effects)
+                if !isempty(callinfos)
+                    callsite = let
+                        ...
+                    end
+                end
```

Approach considered and rejected: patching `process_info`'s `MethodMatchInfo` branch to emit `RTCallInfo` for `nothing` edges. Rejected because `RTCallInfo` represents a *runtime* lookup, which is strictly less informative than the `EdgeCallInfo` the head-dispatch fallback yields for an optimized `:invoke` — the `CodeInstance` is right there in `args[1]`. Better to use the more informative branch.

## Verification

Minimal reproduction (no FFTA dep needed):

```julia
@noinline issue694_b(x::Int) = issue694_a(x - 1)
@noinline function issue694_a(x::Int)
    x <= 0 && return 0
    x > 100 && return issue694_b(x - 1)
    return issue694_a(x - 2) + 1
end
find_callsites_by_ftt(issue694_a, Tuple{Int})
```

- On master: returns `[]` (both `:invoke` statements silently dropped — neither the self-recursive call nor the call to `issue694_b` shows up).
- With fix: returns 2 callsites, `invoke issue694_b(::Int64)::Int64` and `invoke issue694_a(::Int64)::Int64`.

Same root cause as the FFTA `fft_composite!` case — the recursive shape (`fft!` ↔ `fft_composite!`) causes the same all-`nothing`-edges `MethodMatchInfo`.

## Graph state

| Node | Status | Mode | Confidence |
|------|--------|------|------------|
| H₀ — selective IR-stmt filtering | confirmed | induction | 95% |
| H₁ — `MethodMatchInfo` empty-edges + `continue` | confirmed | deduction | 99% |
| Fix — fallthrough to head-dispatch | confirmed | induction (fail-on-master, pass-on-fix repro) | 97% |

## Frontier (open)

- Other `process_info` branches that return `CallInfo[]` (`GlobalAccessInfo`, `OpaqueClosureCreateInfo`, `FinalizerInfo`, `info === false`, `NoCallInfo + Builtin`) all benefit from the same fallthrough — for a `:foreigncall` head we'd hit the jl_new_task path, and for a `:call` head with no head-dispatch handler it's still a no-op (same as previous `continue`). Net effect on these paths: zero or strictly more callsites enumerated. Not separately tested, but the deductive argument is clean.
