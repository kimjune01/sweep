# JuliaDebug/Debugger.jl#394 — Backslash completion broken on Julia 1.12

## Phase 1 — Observation (H₀)

User reports: in Julia 1.12.5, entering `@enter fn()` then `\Omega<tab>` in
the debug REPL throws `MethodError: no method matching
_completion_text(::REPL.REPLCompletions.BslashCompletion)`. Works fine on
1.10. Stack tail:

```
[1] completion_text(c::REPL.REPLCompletions.BslashCompletion)
    @ REPL.REPLCompletions … REPLCompletions.jl:127
[2] iterate generator.jl:48 [inlined]
[3] _collect(…, generator over comps)
[4] completions(c::Debugger.DebugCompletionProvider, …)
    @ Debugger src/repl.jl:250
```

Trajectory shape: **divergent**. Single deterministic failure; not
flaky. Bug is localized to one call site.

## Phase 2 — Fan-out

### H₁ — Debugger calls `completion_text` on a completion type 1.12 no longer supports

Mode: deduction.
Perturbation: read `src/repl.jl` around the line in the stack trace and the
1.10 vs 1.12 versions of `stdlib/REPL/src/REPLCompletions.jl`.

Findings:

- `src/repl.jl:274` and `:284` call `map(REPLCompletions.completion_text, comps)`.
- Julia 1.10 (`release-1.10` REPLCompletions.jl) defines
  `_completion_text(c::BslashCompletion) = c.bslash`. `completion_text`
  dispatches to it cleanly.
- Julia 1.12 (`release-1.12` REPLCompletions.jl) **removes** that method
  and instead defines `named_completion(c::BslashCompletion) =
  NamedCompletion(c.completion, c.name)`. The field also renamed from
  `bslash` → `completion`. `completion_text(c) = _completion_text(c)::String`
  now throws on `BslashCompletion` because no `_completion_text` method
  matches.

Trajectory: **divergent confirmation**. The source diff exactly matches
the reported MethodError. H₁ confirmed.

Kill condition for any rival hypothesis: produce a stack that doesn't
route through `completion_text`. None found.

### Provenance check (Phase 2.5)

- Origin: `src/repl.jl` `completions(::DebugCompletionProvider, …)` has
  used `REPLCompletions.completion_text` since the file was written; this
  isn't a recent regression on Debugger's side. The break is on the
  Julia/REPL side.
- Upstream: Julia 1.12's REPL switched to `named_completion`-based
  routing. The break is intentional REPL refactor; downstream consumers
  (Debugger, other packages with their own `CompletionProvider`) are
  expected to follow.
- No competing PR found: `gh pr list --search "Backslash completion"`
  returned none. Operator has no prior PR on this repo.

## Phase 3 — Extend

Frontier edges considered, all closed by reading code:

- *Does the same break apply to other completion types?* `_completion_text`
  still exists for `Keyword/Path/Module/Package/Property/Field/Method/
  Shell/Dict/KeywordArgument/Keyval/Text`. Only `BslashCompletion` lost
  its method. `named_completion`'s generic fallback (`named_completion(c)
  = NamedCompletion(completion_text(c), completion_text(c))`) routes
  everything else through the same `_completion_text` machinery, so
  swapping in `named_completion` doesn't regress the other types.
- *Does `named_completion` exist on 1.10?* No — added in 1.12. Hence the
  `@static if isdefined(REPLCompletions, :named_completion)` guard.

Frontier closes. Move to fix.

## Phase 5 — Prework

Fix shape: introduce a local `_completion_text` shim in `src/repl.jl`
that uses `REPLCompletions.named_completion(c).completion` when available
and falls back to `REPLCompletions.completion_text` otherwise. Swap the
two `map(REPLCompletions.completion_text, …)` calls to use the shim.

Compat: `named_completion(c).completion` returns the insert-string for
every completion type (for `BslashCompletion`, `c.completion`; for others,
`completion_text(c)`), so the value passed downstream is identical to the
pre-1.12 behavior on 1.10 and is the strictly-more-correct value on 1.12.

## Phase 5.5 — Regression check

- Added regression test (`test/ui.jl`) — `test_complete(prov, "\\Omeg")`
  must include `"\\Omega"`.
- **Fail on master**: `Pkg.test()` reports `REPL completions: Error …
  MethodError: no method matching _completion_text(::BslashCompletion)` —
  exactly the issue's stack.
- **Pass on fix**: `REPL completions | 3 pass / 3 total`. Full suite
  green.

## Phase 6 — Benchmark

N/A — correctness fix, no performance dimension.

## Phase 7 — Bug hunt

Skipped automated codex/gemini round; the fix is two lines of dispatch
plumbing and the compiler+test together cover the failure mode. Manual
adversarial pass:

- *What if a future Julia removes `named_completion` again?* The
  `isdefined` guard reverts to the old path; safe.
- *What if a completion type appears that has neither method?* Same
  MethodError downstream. Not introduced by this fix.
- *Does `named_completion(c).completion` change the displayed text for
  non-Bslash completions?* For 1.12, `named_completion`'s generic
  fallback returns `NamedCompletion(text, text)` where `text =
  completion_text(c)`. Identical to current behavior.

## Phase 8 — Ship

Pipeline mode — readiness record only. `/drip` handles the push and PR.

## Graph state table

| Node | Status | Shape | Mode |
|------|--------|-------|------|
| H₀ user-reported MethodError on 1.12 | confirmed | divergent | induction |
| H₁ Debugger calls `completion_text` on `BslashCompletion`, which lost its dispatch in 1.12 | confirmed | divergent | deduction + source diff |

Frontier: closed.
