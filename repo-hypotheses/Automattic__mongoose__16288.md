# Automattic/mongoose#16288 — `$percentile` missing from `AccumulatorOperator`

## H₀ — observation

User reports `$percentile` triggers `TS2353` inside `$group`, but `$median` (identical shape in MongoDB docs) does not. MongoDB 7.0 ships both as siblings.

Perturbation: grep `Median` and `Percentile` in `types/expressions.d.ts`.

| symbol | interface declared | in `AccumulatorOperator` | in `WindowOperator` | in returning-array union |
|---|---|---|---|---|
| `$median` | yes (Expression.Median) | yes | yes | n/a (scalar) |
| `$percentile` | **no** | **no** | **no** | **no** |

Trajectory: divergent — asymmetry is exact and load-bearing. H₀ killed: the bug is purely missing TS type declarations.

## Causal chain

1. Mongoose's aggregation expression types are hand-maintained per MongoDB release.
2. MongoDB 7.0 introduced `$median` and `$percentile` together.
3. Only `$median` was added to mongoose's type surface.
4. `$percentile` was overlooked. Mongoose passes the pipeline object through to the driver verbatim, so the gap is type-only — no runtime path missing.

## Fix

Mirror the `$median` pattern exactly.

- Add `export interface Percentile { $percentile: { input, p, method } }` next to `Median`.
- Add `Expression.Percentile` to three unions where `Expression.Median` appears, plus `WindowOperatorReturningArray` (since `$percentile` returns an array, unlike scalar `$median`):
  - `AccumulatorOperator` (where the user hit the error)
  - `WindowOperator` (MongoDB allows it in `$setWindowFields`)
  - `WindowOperatorReturningArray` (return type is `number[]`)

Shape per MongoDB BSON spec:
```ts
$percentile: { input: number | Expression, p: number[] | Expression, method: 'approximate' }
```

## Verification (fail-on-master, pass-on-fix)

Test `gh16288` added to `test/types/expressions.test.ts` mirroring `gh15209` style.

- Without fix (`git stash` types/expressions.d.ts): tstyche reports `'$percentile' does not exist in type 'AccumulatorOperator'.ts(2353)` — same error the user reported, verbatim.
- With fix: target passes. A pre-existing `types/index.d.ts:1147` warning persists on both sides — unrelated to this change.

## Reasoning mode

- Deduction (read type files, traced unions): 99% — asymmetry is mechanical.
- Induction (ran tstyche before/after): 95% — local verification matches user-reported error string.

## Frontier

Closed. Type-only, additive, no runtime behavior change, no risk to existing `$median` users.
