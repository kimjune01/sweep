# EnzymeAD/Reactant.jl#2899 — Strange convert arguments for Comrade

**Status**: halted at Phase 4 (report) — human-gated.
**Reason for halt**: bug is in deep tracing/path-traversal logic; the fix surface is `traced_getfield` dispatch + path generators in `make_tracer*` overloads (`src/Tracing.jl`, `src/compiler/Codegen.jl`). Reproducer requires VLBISkyModels + Reactant + XLA runtime, not runnable in `sweep-tester:latest`. Reporter himself is unsure of root cause. Not a ship-without-running case.

## H₀: dispatch failure at path walk
**Observation (deduction, 95%)**: `MethodError: no method matching getproperty(::ConcretePJRTNumber{Float64, 1}, ::Int64)` originates at `src/compiler/Codegen.jl:46`:

```julia
@inline function traced_getfield(
    @nospecialize(obj::Union{AbstractConcreteArray,AbstractConcreteNumber}), field
)
    return Base.getproperty(obj, field)
end
```

The only `getproperty` method on these types accepts `::Symbol`. When `field::Int64` is dispatched the call falls through to `Base.getproperty(::Any, ::Symbol)` and explodes. So either (a) the dispatch is wrong (should use `getfield`/`getindex` for integer field), or (b) the path should never reach this point — the leaf was passed an extra index.

**Kill condition**: find the path generator that produced the extra trailing index past the `ConcretePJRTNumber` leaf, OR confirm `traced_getfield` should branch on `field isa Integer`.

## H₁: trailing-index leak from path-reconciliation branch
**Abduction (75%)** — `make_tracer_via_immutable_constructor` (`src/Tracing.jl:1283-1326`) has a reconciliation path that handles struct-type mismatch (e.g. `Foo{Float64}` → `Foo{TracedRNumber}` arising when a parent type constraint forces the eltype gap the reporter highlighted). The branch only handles the case `is_traced_number(ft_j) && val_j isa unwrapped_eltype(ft_j)` — it appends `sub_path = append_path(newpath, j)` to wrap a scalar (line 1298). If the runtime field happens to already be a `ConcretePJRTNumber` (e.g. because constructor of `PolExp2Map` iterated a `ConcretePJRTArray` whose eltype is `ConcretePJRTNumber{Float64,1}` and stored it directly), the wrapping branch may still append `j` and the leaf path now has a spurious tail.

**Perturbation (not run, requires Julia)**:
1. In the MWE, dump `get_paths(arg)` for each linear arg before `prepare_mlir_fn_args` walks them. Expect a path of shape `(:args, k, fld_i, fld_j, j)` where the last `j` points past a `ConcretePJRTNumber`.
2. If confirmed, the fix is either to short-circuit reconciliation when `val_j` is already a concrete leaf, or to teach `traced_getfield(::AbstractConcreteNumber, ::Integer)` to return the obj (no-op) since concrete numbers are atomic.

## H₂: eltype-divergence in user constructor
**Abduction (60%)** — reporter's own hypothesis (#2869 cross-reference). `eltype(ConcretePJRTArray{Float64}) = Float64` vs `eltype(TracedRArray{Float64}) = TracedRNumber{Float64}`. `PolExp2Map`'s constructor (in VLBISkyModels) likely does scalar reads/stores that get *different* concrete types between the warm and traced calls. The PolExp2Map struct ends up holding a `ConcretePJRTNumber{Float64,1}` where its declared field type is `Float64`. This is the *condition* that activates H₁'s reconciliation path. Fix at the eltype level is more invasive (changes the public surface of Concrete types); fix at the path level (H₁) is the local one.

**Kill condition**: if H₁ is killed because paths are clean, H₂ becomes the load-bearing diagnosis and the fix moves upstream (eltype of concrete types should match traced).

## H₃: `traced_getfield` dispatch is the real defect
**Abduction (55%)** — even if H₁ generates the spurious path, defending in depth at `traced_getfield`'s dispatch is cheap and correct: a concrete number has no integer-indexable subfields; integer-indexing into one is meaningless, so the dispatcher should either (a) return `obj` (treat as atom), (b) call `getfield(obj, field)` (which would land on the internal `data` slot — wrong), or (c) error with a clearer "leaf node, no descent" message that names the path. Option (a) plus the H₁ fix is belt-and-suspenders.

**Kill condition**: confirm that no legitimate caller of `traced_getfield(::AbstractConcreteNumber, ::Integer)` exists. If found, (a) breaks it.

## Frontier edges (open)
- **E₁ (H₁)** — instrument `get_paths` in the MWE and inspect the linear-arg paths. Needs Julia+Reactant+VLBISkyModels. Predicted shape: divergent (one direction wins decisively).
- **E₂ (H₂)** — try a smaller MWE with only `PolExp2Map(am, bm, cm, dm, gimr)` and `@jit identity(mr)` (drop FourierDualDomain/visibilitymap). If the error reproduces, H₂ is the locus. If not, the issue is in `make_mlir_fn` of `visibilitymap` walking a struct it didn't construct. The reporter has not run this isolation — would clarify scope.
- **E₃ (H₃)** — grep callsites of `traced_getfield`; if all paths are constructed only by `make_tracer*`, the defensive fix is safe.

## Reasoning mode table
| Claim | Mode | Confidence |
|-------|------|------------|
| Dispatch failure site is `Codegen.jl:46` | Deduction (read stack trace + source) | 99% |
| Path walk in `prepare_mlir_fn_args` is the call site | Deduction | 99% |
| Reconciliation branch in `make_tracer_via_immutable_constructor` is the path-leak suspect | Abduction | 75% |
| Eltype divergence is the precondition that activates the leak | Abduction (reporter-corroborated) | 65% |
| Fix at `traced_getfield` is defensive but correct | Abduction | 60% |

## Pruning log
- (none) — no perturbations run (no live Reactant). Hypotheses all open.

## Related
- #2869 ("Another StructArray issue") — same eltype-mismatch family. Same `prepare_mlir_fn_args` callsite line range. Different leaf type (NamedTuple convert vs concrete-number getproperty) but the shared root is "tracer didn't unify Concrete↔Traced eltype semantics."
- #2900 (jumerckx) — unrelated; addresses #2853, traced loop body argument duplication.

## Recommendation
Two-track fix worth the maintainer's attention:
1. **Local (cheap)**: add `traced_getfield(::AbstractConcreteNumber, ::Integer) = obj` (or a clearer error) in `src/compiler/Codegen.jl`. Keeps dispatch from blowing up on stray integer indices into atomic concrete leaves.
2. **Upstream (correct)**: in `make_tracer_via_immutable_constructor`'s reconciliation branch (`src/Tracing.jl:1283-1326`), short-circuit when `val_j` is already a concrete leaf rather than wrapping it and appending a sub-path.

The minimal one-line defensive fix (track 1) would likely make the reporter's MWE proceed past the dispatch error; track 2 fixes the structural cause. Maintainer should pick — both have small radii but the choice is theirs.

**Halt**: not shipping a PR. Required: Julia + Reactant + VLBISkyModels env to reproduce, run perturbations against H₁/H₂/H₃, and verify the fix doesn't regress the broader test suite. Hand off to operator (or to investigate-with-Reactant-env).
