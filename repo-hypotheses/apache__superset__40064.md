# Hypothesis Graph: apache/superset#40064

Fixes upstream #36530 (sfirke, "Histogram throws warning in logs in 6.0.0rc4", labeled `good first issue`).

## State
- PR open since 2026-05-12. CI fully green (unit, integration, E2E, Cypress, Playwright, CodeQL, pre-commit). `reviewDecision: REVIEW_REQUIRED`. No human maintainer engagement; only bot comments (Bito, codecov, netlify).
- Branch: `fix/setting-with-copy-warning` → `master`.
- 4 files changed, +40/-4 lines.

## H₀ — `SettingWithCopyWarning` is two separate chained-assignment bugs
- **Mode**: deduction (read the traceback + read the code paths).
- **Perturbation**: ran `pytest` with `warnings.simplefilter("error", SettingWithCopyWarning)` on both postprocessing entry points.
- **Trajectory**: divergent — the warning fires every time under the promoted-to-error harness, regardless of input shape.
- **Verdict**: confirmed. Two separate sites, both classic pandas chained-assignment.
  1. `boxplot.py:130` — `df[column] = to_numeric(...)` against a sliced `df`.
  2. `histogram.py:51` — assignment after `dropna()` which can return a view.

## H₁ — `df.loc[:, column]` resolves the boxplot site
- **Mode**: induction (the test now passes under the error-promoted harness).
- **Perturbation**: rewrite to `df.loc[:, column] = to_numeric(df[column], errors="coerce")`.
- **Trajectory**: divergent for — clean pass, semantics identical (boxplot only reads aggregates downstream).
- **Verdict**: confirmed.

## H₂ — `dropna().copy()` resolves the histogram site
- **Mode**: induction.
- **Perturbation**: append `.copy()` to the `dropna(subset=[column])` call.
- **Trajectory**: divergent for. The copy is on the already-filtered subset, so the memory overhead is bounded by surviving rows, not the input.
- **Verdict**: confirmed.

## H₃ — Pre-existing test mutation hazard in `test_boxplot_type_coercion`
- **Mode**: abduction → induction.
- **Observation**: the original test mutated module-level `names_df` without `.copy()`; this leaked across tests when the new regression test added the same fixture.
- **Perturbation**: add `.copy()` to the existing test.
- **Trajectory**: convergent — no other test in the file mutates `names_df`, so the cleanup is local.
- **Verdict**: confirmed, shipped in the same PR (deliberate; not scope creep — it would have been a flake source for the new test).

## H₄ — Bito's `copy(deep=False)` suggestion
- **Mode**: abduction by a third-party bot reviewer.
- **Claim**: shallow copy is cheaper on wide DataFrames and still breaks the view chain.
- **Perturbation (deduction-only)**: read pandas docs — `DataFrame.copy(deep=False)` shares data buffers but creates a fresh `_is_copy` weakref, which is what breaks the chained-assignment warning path.
- **Trajectory**: convergent in theory, but the input here is the already-filtered post-`dropna` subset; the wide-DataFrame argument doesn't apply. Reaching for `deep=False` is a micro-optimization the maintainer didn't ask for.
- **Verdict**: killed. Memory: feedback_no_unrequested_features — render exactly what the issue asks. Bot suggestion ignored.

## Provenance check
- Origin of the warning: `boxplot.py:130` and `histogram.py:51` both predate pandas 1.5 (when `SettingWithCopyWarning` started firing reliably on these patterns).
- Issue reporter (`sfirke`) is a long-time pandas contributor (author of `janitor`); the framing in the issue ("just something to clean up") suggests low-friction acceptance is expected.
- No competing PR found via `gh pr list --search "SettingWithCopyWarning"` on apache/superset.
- Label `good first issue` on #36530 — maintainers explicitly invited an outside contributor.

## Frontier edges
- **E₁ (open, waiting on external signal)**: maintainer review. No technical perturbation available from our side. Predicted trajectory: convergent-merge given clean CI + tests + small diff + invited-fix posture. Confidence: medium (Apache projects can be slow on `good first issue` PRs even when ready).
- No other open hypotheses. The technical investigation is closed.

## Halt
Investigation halts: frontier closed on the technical axis. The remaining edge is human attention, which isn't a perturbation we own. No prework needed — the fix is already shipped and green.
