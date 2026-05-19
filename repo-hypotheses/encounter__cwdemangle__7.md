# encounter/cwdemangle#7 — Templated function pointer

**Issue:** `allocatorAlloc__Q34util17Delegate<Fv_v,64>12DelegateHeapFUll` fails to demangle. RootCubed (commenter) ran c++filt on the GCC equivalent and confirmed expected output: `util::Delegate<void (), 64>::DelegateHeap::allocatorAlloc(unsigned long, long)`.

## H₀ — Reproduce on master
- **Perturbation:** `cargo run -p cwdemangle-bin -- 'allocatorAlloc__Q34util17Delegate<Fv_v,64>12DelegateHeapFUll'`
- **Result:** `Error: "Failed to demangle symbol"` — divergent against demangler.
- **Trajectory:** divergent. Bug is real.

## H₁ — `F` (function type) in template arg with no preceding `P` returns None
- **Trace:** `find_split` correctly skips `__` inside `<…>`, lands at `__` after `allocatorAlloc`. The qualified-name parser reaches template-arg `Fv_v`. `demangle_arg("Fv_v,64")` enters the `F` branch at lib.rs:202. `is_member=false`, `post=""` (no `P` prefix), so `post.starts_with('*')` is false → falls through to `return None` at lib.rs:218.
- **Reasoning mode:** deduction (read the code).
- **Status:** confirmed.
- **Provenance:** the `else { return None }` branch was introduced from the start (single-author repo, encounter). No prior PR addresses function-type-literal template args (verified: no related PRs in pack). MWCC encodes function pointer as `PF…`, function type literal as `F…` directly. Symbol-form is legal MWCC output for `template <typename T>` where `T = void()`.

## Fix design
Replace the `return None` branch with a function-type-literal handler that formats as `<ret> (<args>)` (no `(*)` wrapper). This is purely additive — the existing path returned `None`, so no existing successful test can regress.

Honor `omit_empty_parameters`: `Fv_v` with the option on → `void ()`, off → `void (void)`. Mirrors the top-level convention.

## Fix verification
- master: `Error: "Failed to demangle symbol"` (recorded H₀).
- fix: `util::Delegate<void (), 64>::DelegateHeap::allocatorAlloc(unsigned long, long)` — matches c++filt and matches reporter's amended expectation.
- All 8 pre-existing tests still pass.
- New regression test added covering both the reporter's symbol and `omit_empty_parameters=false` formatting.

## Reasoning mode table
| Claim | Mode | Confidence |
|---|---|---|
| Symbol is valid MWCC mangling for `void()` template param | abduction + c++filt cross-check | 95% |
| `else { return None }` is the immediate cause | deduction (code trace) | 99% |
| Fix is additive (no existing path returned a value here) | deduction | 99% |
| New behavior matches c++filt | induction (ran it) | 99% |

## Frontier (open)
- Nested/complex return types in plain `F` template args (e.g., `FPCc_v` literal) — covered by the same fix; tested implicitly by reusing `demangle_arg` recursion.
