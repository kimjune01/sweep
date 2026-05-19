# JuliaDebug/Cthulhu.jl#701 — "Colours don't work in Julia 1.12"

Issue body: with `@descend times((1,2),(2,3))` (a function that produces a `Core.Box`-captured local), in Julia 1.11 the `index` slot shows in **bright red** as `::Core.Box`; in Julia 1.12 "everything appears blue".

## Local environment

- Julia: 1.12.6 (host)
- Cthulhu: 3.0.2 (master, commit `a8da271d`-area)
- TypedSyntax: 1.5.4
- Repro driver: `Cthulhu.Testing.VirtualTerminal` with `:color => true`

## Graph state

| Node | Hypothesis | Status | Trajectory | Notes |
|------|-----------|--------|-----------|-------|
| H0   | The repro produces no red on 1.12 (literal restatement of issue) | **partial** | convergent (cyan-only when iswarn=false) | with `@descend` defaults, `::Core.Box` renders cyan, matching the user's complaint, BUT this is also true on 1.11 with the same defaults |
| H1   | `is_type_unstable(Core.Box)` regressed on 1.12 | **killed** | divergent | direct test on 1.12.6: returns `true` (Core.Box → `!isdispatchelem ⇒ false`, `type == Core.Box ⇒ true`) |
| H2   | `printstyled(::TypedSyntaxNode; iswarn=true)` no longer colors unstable types red on 1.12 | **killed** | divergent | direct call on 1.12.6 prints `\e[31m::Core.Box\e[39m` — bright red |
| H3   | `@descend iswarn=true` doesn't propagate iswarn to TypedSyntax rendering on 1.12 | **killed** | divergent | confirmed via VirtualTerminal — `@descend iswarn=true terminal=…` produces red `::Core.Box`, red `::Any`, cyan `::Tuple{Int64, Int64}`, exactly as on 1.11 |
| H4   | Interactive `w`-toggle does not flip color rendering on 1.12 | **killed** | divergent | sequence `wq` against VirtualTerminal produces the first frame in cyan, second frame (after `w`) in red. Toggle works. |
| H5   | User confused `@descend` (iswarn=false default) with `@descend_warntype` (iswarn=true default), and on 1.12 something else also subtly changed | **partial / unresolved** | suggestive | `@descend`'s `iswarn` default has been `false` in every version reachable in `git log` (back through `0d4a949~1`, Oct 2025). For the user to have seen red on 1.11, they either ran `@descend_warntype`, toggled `w`, or saved `iswarn=true` via `save_config!`. |
| H6   | Result of `cthulhu_typed` source-view path on 1.12 routes to `devnull` due to `jump_always && inlay_types_vscode`, swallowing all output | **killed** | divergent | defaults: `jump_always=false` → `source_io` is `lambda_io`, output is emitted normally and shows in repro |
| H7   | Some Julia-1.12-only stdlib (`JuliaSyntaxHighlighting v1.12.0`, auto-loaded) overrides ANSI escape rendering inside the source view, neutralizing iswarn red | **open** | not tested | plausible: `JuliaSyntaxHighlighting` ships with 1.12, isn't present in 1.11. Cthulhu's source view path doesn't currently call it, but `Base.show`/stdout layering could be touched. Would need a 1.11 install to A/B. |

## Reproduction transcript (1.12.6, default `@descend`)

```
11      index[36m::Core.Box[39m = 0
12      while (v[36m::Tuple{Int64, Int64}[39m[end-index][36m::Core.Const(2)[39m == w[36m::Tuple{Int64, Int64}[39m[1+index][36m::Any[39m)[36m::Any[39m
…
16      return ntuple(…)[36m::NTuple{4, Any}[39m
```

All annotations are `\e[36m` (cyan). This matches the user's "everything blue" — `:cyan` in the default terminal palette is a blue-leaning teal that many people read as "blue".

## Reproduction transcript (1.12.6, `@descend iswarn=true`)

```
11      index[31m::Core.Box[39m = 0
12      while (… [end-index][36m::Core.Const(2)[39m == … [1+index][31m::Any[39m)[31m::Any[39m
…
16      return ntuple(…)[31m::NTuple{4, Any}[39m
```

`\e[31m` (bright red) for unstable types, `\e[36m` (cyan) for stable. **Identical to the 1.11 behavior described in the issue.**

## Causal chain

Observation H0 (everything cyan on 1.12) is reproducible. H1–H4 systematically rule out:
- regression in the `Core.Box` predicate
- regression in `printstyled(::TypedSyntaxNode)`
- regression in `@descend`'s plumbing of `iswarn`
- regression in the `w` toggle

The most consistent explanation is **H5: the user's 1.11 run had `iswarn=true` (via `@descend_warntype`, an in-session `w` toggle, or `save_config!`-stored preference), and their 1.12 run has `iswarn=false`** — perhaps because the LocalPreferences file moved or wasn't picked up, or because the user is comparing different invocations.

H7 (JuliaSyntaxHighlighting layering) is the only frontier edge that could yield a real 1.12-specific regression. Requires a Julia 1.11 install for an A/B; not available in this environment.

## Frontier edges

- **E1 (open):** A/B on Julia 1.11.x with the same `Project.toml`, `LocalPreferences.toml`, and exact reproducer. Goal: confirm whether 1.11's `@descend` (defaults) produces red or cyan. If cyan in both → H5 confirmed, no bug to fix; if red on 1.11 and cyan on 1.12 with identical config → genuine regression, follow H7.

## Reasoning mode table

| Node | Mode | Confidence |
|------|------|-----------|
| H0   | induction (ran the repro) | 99% |
| H1   | deduction + induction | 99% |
| H2   | induction | 99% |
| H3   | induction | 99% |
| H4   | induction | 99% |
| H5   | abduction | 60% |
| H6   | deduction | 95% |
| H7   | abduction | 25% |

## Pruning log

- H1: killed by direct call to `is_type_unstable(Core.Box)` returning `true`.
- H2: killed by direct `printstyled(io, tsn; iswarn=true)` producing `\e[31m::Core.Box\e[39m`.
- H3: killed by `@descend iswarn=true terminal=…` rendering red.
- H4: killed by `wq` keystroke sequence in VirtualTerminal producing red on the redisplayed frame.
- H6: killed by reading the default config (`jump_always=false`) — guard is not entered.

## Verdict

**No fix to ship.** Cannot reproduce a 1.12-specific regression with the current master. Default `@descend` has always rendered annotations in cyan (iswarn=false), and `@descend iswarn=true` correctly renders unstable types in red on 1.12.6.

Most likely the user's 1.11 reference run had `iswarn=true` (via `@descend_warntype`, an in-session `w` toggle, or stored preferences) and the 1.12 run is using defaults, making the rendering difference attributable to configuration drift rather than a Cthulhu bug.

Route: `tissue` — ask the user to confirm whether they saw red on 1.11 with literally `@descend` (no kwargs, no prior `w` toggle, no `save_config!`), and whether `@descend iswarn=true` on their 1.12 install also shows cyan.
