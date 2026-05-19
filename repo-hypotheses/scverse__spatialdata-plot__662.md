# Hypothesis graph — scverse/spatialdata-plot#662

## Issue

`make_palette_from_data(sdata, element, color)` raises `KeyError` when `element` is a labels (raster) element. The error message itself flags this as "not yet supported" — a known TODO, not a principled exclusion.

## H₀ — `_resolve_element` rejects labels at the dispatch site

- **Hypothesis:** the gap is purely at `src/spatialdata_plot/pl/_palette.py:289-306`, where the dispatch only handles `sdata.shapes` and `sdata.points`. For labels, the categorical column always lives on the linked AnnData table — no GeoDataFrame branch needed.
- **Perturbation:** read the file; trace what happens for a labels element.
- **Trajectory:** divergent confirming. The function raises at line 303-306 before any table lookup can happen. The existing `_get_labels_from_table` helper (line 312) is structure-complete — it already (a) iterates `sdata.tables`, (b) filters by `region` membership, (c) handles ambiguous-table → ValueError, (d) honours `table_name=` override. It does not depend on shapes/points specifically.
- **Conclusion:** add a `elif element in sdata.labels` branch that calls `_get_labels_from_table` directly. ~5 LOC + error message + test.

## Provenance

- `_resolve_element` was added with the rest of `_palette.py` in the make_palette feature set; the `"not yet supported"` wording is from the original author (timtreis, the reporter). Same author opened the issue against their own code — explicit TODO carryforward, no architectural objection to resolve.
- Operator has no prior PRs on this repo.
- No competing open PRs mention `make_palette_from_data` for labels.

## Causal chain

Dispatch rejects labels → `_get_labels_from_table` is never reached → user sees KeyError despite `render_labels(palette=...)` accepting palettes for the same element.

## Fix

1. Add `elif element in sdata.labels:` branch in `_resolve_element` that calls `_get_labels_from_table` directly (labels have no element-level column to check; table is the only source).
2. Widen the `Available elements` / error message to include `sdata.labels.keys()` and drop the "not yet supported" footnote.
3. Update `make_palette_from_data` docstring `element` param: "shapes or points element" → "shapes, points, or labels element".
4. Add a regression test mirroring `test_shapes_with_table` for a labels element annotated by a table with a categorical column.

## Frontier edges

- None open. Single-branch dispatch, single-test coverage. Open questions in the issue (NaN handling, multi-table ambiguity) are already handled by `_get_labels_from_table` and the upstream categorical conversion — no new code path.

## Reasoning modes

| Claim | Mode | Confidence |
|---|---|---|
| Dispatch is the only gap | Deduction (read the code) | 98% |
| `_get_labels_from_table` works unchanged for labels | Deduction (it queries tables, not element type) | 95% |
| ~5 LOC + 1 test | Abduction | 85% |
