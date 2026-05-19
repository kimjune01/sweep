# Hypothesis Graph: GreptimeTeam/promql-parser#145

Date: 2026-05-19
Repo: GreptimeTeam/promql-parser
Issue: #145 - Enforce additional check for info function
Status: fix ready (Phase 8 awaits drip)

## Issue restated

Prometheus enforces extra restrictions on the experimental `info()` function:
type-check arg #2 as Vector, require it to be a `*VectorSelector` with empty
`Name` (label-selectors only), and set `BypassEmptyMatcherCheck` so `info(x, {})`
is valid. promql-parser doesn't define `info` at all today, so even arity
checking is missing.

## Graph State Table

| Node | Status | Trajectory | Summary |
|---|---|---|---|
| H0 | killed | divergent | "Repo can be perturbed locally" — was false (no worktree). Now true after clone. |
| H1 | confirmed | divergent | `info` is absent from `FUNCTIONS`; parse fails with `unknown function 'info'`. |
| H2 | confirmed | divergent | Adding `info` with `(Vector, Vector), variadic=1, experimental=true` reproduces Prometheus's arity bounds (>=1, <=2). |
| H3 | confirmed | divergent | `check_ast_for_call` already runs the per-arg type loop; an info-specific structural check placed *after* it matches Prometheus's error ordering (type error wins over label-only error). |
| H4 | partial | convergent | `BypassEmptyMatcherCheck` equivalent — promql-parser's `check_ast_for_vector_selector` rejects empty-matcher selectors bottom-up before the call-level check sees them. Scope-out for this PR; flag as follow-up. |

## Nodes

### H1 — `info` is undefined in FUNCTIONS

- Perturbation: `grep -rn '"info"' src/` → no hits in `function.rs`.
- Trajectory: parse of `info()` returns `unknown function with name 'info'`.
- Kill: `info` must be added to the static `FUNCTIONS` map before any further check applies.
- Edge → H2.

### H2 — Arg-types and variadic shape match Prometheus

- Perturbation: add `function!("info", vec![Vector, Vector], 1, Vector, true)`.
- Trajectory: `info()` → "expected at least 1"; `info(a,b,c)` → "expected at most 2"; `info(a, 1)` → "expected type vector". All match Prometheus error wording.
- Kill: arity & type errors are now emitted by the generic path; no info-specific code needed for them.
- Edge → H3.

### H3 — Structural check ordering

- Perturbation A: structural check placed *before* per-arg type loop.
  - Trajectory: `info(x, 1)` reports "expected label selectors only" instead of the Prometheus-style "expected type vector ... got scalar". Oscillatory against the Prometheus error contract.
- Perturbation B: structural check placed *after* per-arg type loop.
  - Trajectory: `info(x, 1)` → "expected type vector ... got scalar"; `info(x, some_metric)` → "expected label selectors only, got vector selector instead"; `info(x, sum(m))` → "expected label selectors only". Converges with Prometheus's emission order.
- Kill: option A. Ship option B.

### H4 — BypassEmptyMatcherCheck (scoped out)

- Observation: `check_ast_for_vector_selector` runs bottom-up via grammar productions (`promql.y`), so by the time `check_ast_for_call` runs, `info(x, {})` has already been rejected as "vector selector must contain at least one non-empty matcher".
- Implementing the bypass requires either:
  1. A `bypass_empty_matchers` field on `VectorSelector` set by the grammar/call rule before child validation, or
  2. Two-pass validation (build AST first, then check_ast after).
- Both are larger structural changes; the maintainer's ask in the issue says "Address this in our arity check as well" — covered by H2+H3. Defer the bypass to a follow-up if requested in review.

## Provenance

- `info` function was added upstream in prometheus/prometheus#14495 (PromQL "info" function, experimental). The restrictions block is in `promql/parser/parse.go` ~`checkAST`.
- promql-parser tracks Prometheus's function table but did not include `info` when its limitk/limit_ratio cohort was added (see #141, #143 chore-bump). Gap, not deliberate exclusion.

## Reasoning Mode Table

| Claim | Mode | Confidence | Provenance |
|---|---|---:|---|
| `info` is missing from FUNCTIONS | Induction | 99% | grep + parse error message |
| `(Vector, Vector), variadic=1, experimental=true` matches Prometheus | Deduction | 95% | Prometheus functions.go (the maintainer pasted equivalent Go) |
| Structural check after type check matches Prometheus error ordering | Deduction | 95% | Prometheus parse.go `Args[1].Type()` check precedes the VectorSelector check |
| Tests fail on master, pass with fix | Induction | 99% | Stash + cargo test verified locally |

## Frontier Edges

| Edge | Status | Next |
|---|---|---|
| BypassEmptyMatcherCheck for `info(x, {})` | deferred | Wait for review signal before expanding scope |

## Phase 5.5 Regression check

- `cargo test --lib` in `sweep-tester:latest`: 111 passed, 0 failed.
- `cargo test --lib parser::parse::tests::test_function_call`:
  - On master (test-slice cherry-picked): FAIL ("unknown function 'info'").
  - With fix: PASS.
- Diff: +45 lines across 3 files; no signature changes; no behavioral changes for non-`info` paths.

## PR readiness

- Base: `main` @ `2e4ebde7cef1351459229b2fbca4822c43d0cdfc`
- Branch: `fix/info-arity-check`
- Title: `feat: add info function with Prometheus-aligned arity and label-selector checks`
- Summary: Adds the experimental `info` function to the function table and enforces Prometheus's additional restriction that the second argument, when present, must be a label-only vector selector.
- Tests added in `parse.rs` cover: too-few args, too-many args, type mismatch on arg 2, vector-selector-with-metric-name on arg 2, and an arbitrary vector expr on arg 2.
- Follow-up note for PR body: `BypassEmptyMatcherCheck` equivalent is deferred (would require structural changes to bottom-up VectorSelector validation); happy to follow up if maintainer wants it in this PR.
