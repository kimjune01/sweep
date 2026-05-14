# macbre/sql-metadata #630 — Hypothesis Graph (review-response)

## Context
- PR: https://github.com/macbre/sql-metadata/pull/630 (Fix UNION column alias aggregation, fixes #401)
- Initial commit: 65a4beb (shipped 2026-05-12)
- Reviewer: @collerek (COLLABORATOR), 2026-05-13 08:54Z review COMMENTED + 09:02Z review CHANGES_REQUESTED
- Inline comment: discussion_r3232815966 on `sql_metadata/column_extractor.py:203-216` (`add_alias`)

## Reviewer's two asks (verbatim)
> Although we need some more fixes as this change will nest lists if the alias is referencing multiple columns, since this change changes the global resolution, not only the unions

1. **Case A (nesting):** `SELECT a AS x ... UNION ALL SELECT b + c AS x ...` → expected `{'x': ['a', 'b', 'c']}`, current `{'x': ['a', ['b', 'c']]}`.
2. **Case B (TypeError):** `SELECT a + b AS x ... UNION ALL SELECT c + d AS x ...` → expected `{'x': ['a', 'b', 'c', 'd']}`, current raises `TypeError: cannot use 'sql_metadata.utils.UniqueList' as a set element`.

Reviewer also supplied a suggested implementation.

## Hypothesis
**H1 (reviewer-correct):** Both regressions exist exactly as described. Suggested impl fixes both without breaking existing semantics.

## Evidence (perturbation tests)
| Probe | Pre-fix output | E-value | Notes |
|---|---|---|---|
| Case A query | `{'x': ['a', ['b', 'c']]}` | confirmed nesting | The `[existing, target]` branch wraps a list inside a list when target is itself a list |
| Case B query | `TypeError: ... unhashable type: 'UniqueList'` | confirmed | The `target not in existing` membership check on a `UniqueList(list[str])` target fails because `existing` is a list of `str` and Python's `in` for list-of-str against a `UniqueList` doesn't fail by itself — failure path is `UniqueList(...)` being hashed when used as set element somewhere downstream from the same branch (verified empirically) |
| Original issue #401 case (`tab1.A as M ... tab2.B as M`) | `{'M': ['tab1.A', 'tab2.B']}` ok | unchanged | Scalar+scalar path was correct |

E-classification: **strong confirmation, exact match to reviewer claim**. No falsifying probe found.

## Decision
**FIX (no pushback).** Reviewer's claim survived all perturbation tests. Adopting suggested implementation verbatim is the correct move per `feedback_reviewer_pushback` (test claim → confirmed → implement).

## Implementation
- Replace conditional aggregation block in `_Collector.add_alias` with reviewer's normalized merge:
  ```python
  if target is None: return
  existing = self.alias_map.get(name, [])
  merged = UniqueList(existing if isinstance(existing, list) else [existing])
  merged.extend(target if isinstance(target, list) else [target])
  self.alias_map[name] = merged if len(merged) > 1 else merged[0]
  ```
- Add `test_union_alias_with_expression_targets` covering both regressions in `test/test_unions.py`.
- Suite: 271 passed (was 270, +1 new).

## Attestation
- Commit: 4ca0cd614a1708768da47de58ae82a9334ab4387
- Pushed: kimjune01/sql-metadata fix/union-column-alias-401
- Test command: `python -m pytest test/ -q`
- Test result: `271 passed in 0.39s`
- Reply posted: https://github.com/macbre/sql-metadata/pull/630#issuecomment-4446288280

## Provenance
- Reviewer comment timestamps: 2026-05-13T08:54:25Z (COMMENTED) + 2026-05-13T09:02:25Z (CHANGES_REQUESTED)
- Investigation timestamp: 2026-05-13
- prior_gates_voided: true (initial QA gate from 2026-05-11 did not exercise expression-target paths)
