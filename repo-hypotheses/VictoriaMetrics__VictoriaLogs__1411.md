# VictoriaMetrics/VictoriaLogs#1411 — Sorting NaN: document the behavior

## Issue framing

Reporter observed: with `sort ... desc`, NaN values appear above numeric values; with `sort ... asc`, numeric values precede NaN. Asks whether bug or expected, and asks for documentation either way. Maintainer @func25 responded: behavior is intentional — sort compares as numbers only when both values are valid numbers; if one is NaN, falls back to natural string sorting. Maintainer agrees this should be documented in the sort pipe docs.

Labels: `documentation, enhancement`. The maintainer has already classified this as a docs ask, not a code bug.

## H₀: the maintainer's described behavior matches the code

- **Mode:** deduction (read the source)
- **Perturbation:** read `lib/logstorage/pipe_sort.go` around the row-comparison hot path.
- **Evidence:** `pipe_sort.go:749-786` — try int64 first (skips if either is 0), then float64 *guarded by `!math.IsNaN(fA) && !math.IsNaN(fB)`*, then natural-string fallback. When either is NaN, the float64 branch is skipped entirely and string fallback runs.
- **Trajectory:** divergent confirm.
- **Status:** confirmed.
- **Consequence:** the maintainer's explanation is accurate. With `desc`, the string fallback puts "NaN" (capital N) high — `LessNatural` compares character-by-character, and uppercase 'N' sorts above digit chars in natural order, which puts NaN entries first under desc. The user's observation is explained.

## H₁: docs page already covers NaN — patch is unnecessary

- **Mode:** induction (grep the docs)
- **Perturbation:** `grep -i nan docs/victorialogs/logsql.md`.
- **Evidence:** no NaN mention near the sort pipe section (`docs/victorialogs/logsql.md:3342-3434`). Issue reporter explicitly links to the same anchor and asks for documentation.
- **Trajectory:** divergent against.
- **Status:** killed. Doc change is warranted.

## Diagnosis

Add a short paragraph (and optionally a CHANGELOG entry) to the `sort pipe` section describing how NaN values are handled. Keep it tight: explain when the numeric path triggers (both values valid numbers), the fallback (natural string sort), and the resulting placement under asc/desc. Match the surrounding docs voice — declarative, no apology, no caveats beyond what's true.

## Provenance

- `pipe_sort.go:765` NaN guard was added at the same time the float64 path was introduced; not a recent regression. Maintainer-acknowledged design choice.
- No related open PRs touch this area (context pack).

## Plan

1. Add a paragraph after the `order` alias example (around line 3378) describing NaN sort behavior.
2. Add a CHANGELOG entry under the unreleased VictoriaLogs section.

## Frontier

Closed. Single docs commit ships.
