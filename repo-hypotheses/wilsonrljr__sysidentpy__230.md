# Hypothesis Graph: wilsonrljr/sysidentpy#230 (reinvestigation)

**PR:** Add include_bias option to Polynomial basis function
**Branch:** add-include-bias-polynomial
**Trigger:** reinvestigate-from-attest. Codacy ACTION_REQUIRED + competing PR #197 surfaced.

## H₀: PR #230 is backward-compatible with `include_bias=True` default

- **Null:** PR changes default behavior of `Polynomial.fit`.
- **Perturbation:** run upstream `test_fit_polynomial` in `sysidentpy/basis_function/tests/test_basis_functions.py` against our branch in `sweep-tester:latest`.
- **Trajectory:** divergent against H₀. Test fails:
  ```
  shapes (2, 6), (2, 4) mismatch
  EXPECTED: [[ 4,  6,  8,  9, 12, 16], [ 9,  9,  9,  9,  9,  9]]
  GOT:      [[ 1,  9, 12, 16], [ 1,  9,  9,  9]]
  ```
- **Kill:** H₀ killed. Default `include_bias=True` is NOT backward-compatible.
- **Mode:** induction (ran the test, measured). ~95% confidence.

## H₁: Bug is in `fit`'s reshape of the input

- **Reasoning (deduction):** original `fit` was `psi = self._evaluate_terms(data, predefined_regressors); return psi[max_lag:, :]`. `_evaluate_terms` uses `combinations_with_replacement(range(n_features), degree)` where `n_features = data.shape[1]` and `data` already includes a bias column at index 0 (placed there by `utils.information_matrix.build_input_output_matrix`). The bias index participates in all cross-products. For degree=2, n=3: 6 combos = `(0,0), (0,1), (0,2), (1,1), (1,2), (2,2)` = `[1, col1, col2, col1², col1·col2, col2²]`.
- **Our PR's diff:** does `data_no_bias = data[max_lag:, 1:]` then `_evaluate_terms(data_no_bias)`. Now n_features = data.shape[1] - 1. For the same example, 3 combos = `(0,0), (0,1), (1,1)` = `[col1², col1·col2, col2²]`. Prepending one bias gives 4 columns. Lost: linear terms `[col1, col2]` and the pure constant comes from prepend, not the (0,0) tuple.
- **Trajectory:** divergent against PR's claim of backward compat. Confirmed.
- **Mode:** deduction (code trace + `test_fit_polynomial` agreement). ~99% confidence.

## H₂: Maintainer's intent is sklearn-style — drop ONLY the (0,0,...,0) pure-bias tuple

- **Evidence (provenance):** maintainer comment on competing PR #197 (poglesbyg, 2025-07-17):
  > "Currently, you added the `include_bias` argument in the Polynomial class, but by default, the method already includes a bias column. In your implementation, when setting `include_bias=True`, it ends up adding an extra bias column alongside the bias already included in the data passed to fit, causing redundancy."
  > "we will need to adjust the `regressor_code` handling logic in the `RegressorDictionary` class (`narmax_base.py`) to respect `include_bias=False` when the user opts out of including the bias."
- **Interpretation:**
  - `include_bias=True` (default) MUST be identity to original behavior — no extra bias prepended.
  - `include_bias=False` drops the (0,0,...,0) combination from BOTH `Polynomial.fit`'s psi AND `regressor_space`'s regressor_code, keeping them in lockstep (mss algorithms iterate over both).
- **Mode:** abduction from maintainer guidance + deduction over code structure. ~90% confidence.

## H₃: Competing PR #197 is alive but stalled

- **Evidence:** PR #197 open since 2025-05-31, CONFLICTING, last activity 2026-03-31 (likely codacy bot rerun). One maintainer comment 2025-07-17 with clear instructions; author never responded.
- **Implication:** Maintainer wanted this issue closed but the work stalled. Our PR #230 has a chance if it correctly implements the maintainer's guidance.
- **Mode:** induction (read PR state + comments). ~95% confidence.

## Fix shape

1. `_polynomial.py`: revert to original fit path on default. For `include_bias=False`, drop col 0 of psi (the (0,0,...,0) tuple). Apply `predefined_regressors` against the resulting index space.
2. `narmax_base.py: regressor_space`: when `self.basis_function` is `Polynomial` and not `include_bias`, drop row 0 of `regressor_code` so it stays aligned with psi columns.
3. Tests: revise our test_polynomial.py to match correct semantics (default == identity; include_bias=False == drop col 0).

## Frontier / open edges

- Whether `predefined_regressors` semantics under `include_bias=False` should re-index (drop 0 from incoming indices) or shift (subtract 1). Current choice: re-index — external indices address the bias-dropped candidate set, mss callers already use `regressor_space()` which is also bias-dropped, so the two stay in lockstep.
- Codacy's 11 "high security" issues — likely false positives on `np.random.rand` in tests (B311). Not a merge blocker for this repo; merged PRs (#226, #228) also have non-passing Codacy.
- regressor_code filtering for non-Polynomial bases: out of scope. They don't share the combinations representation.

## Reasoning mode table

| Claim | Mode | Confidence |
|---|---|---|
| Default behavior broke `test_fit_polynomial` | induction | 95% |
| Original fit operates on combinations including bias | deduction | 99% |
| Maintainer wants identity at default, drop (0,0,…0) at False | abduction | 90% |
| `regressor_space` must mirror the drop | deduction | 90% |
