# Triage Graph: scverse/pertpy

**Repository**: scverse/pertpy (310 stars, Python)
**Description**: Perturbation analysis toolkit for single-cell data
**Date**: 2026-05-11
**Total Issues**: 38 open

## Investigated Issues

### #755 - buggy defaults for plot_multicomparison_fc (FIXED)
- **Type**: Bug
- **Status**: Queued for PR
- **Branch**: fix-plot-multicomparison-fc-755
- **Hypothesis**: H2 (mechanical acceptance)
- **Evidence**: Simple fix - ensure tick labels are visible in heatmap
- **Root Cause**: seaborn heatmap hides labels with small figsize, causing code to fail when plotting significance markers
- **Fix**: Force xticklabels=True and yticklabels=True by default
- **Test**: Added regression test with default figsize
- **Confidence**: High - clear bug, clear fix, test added

### #780 - plot_effects_umap fails after running scCODA (FIXED)
- **Type**: Bug
- **Status**: Queued for PR
- **Branch**: fix-plot-effects-umap-780
- **Hypothesis**: H2 (mechanical acceptance)
- **Evidence**: scCODA uses "Final Parameter" column, tascCODA uses "Effect" column
- **Root Cause**: Code assumed "Effect" column always exists
- **Fix**: Detect which column is present ("Effect" or "Final Parameter")
- **Test**: Added regression test for scCODA plot_effects_umap
- **Confidence**: High - clear incompatibility, clean fix

### #693 - Model doesn't complain if complex interaction contrast is zero (FIXED)
- **Type**: Bug
- **Status**: Queued for PR
- **Branch**: fix-zero-contrast-693
- **Hypothesis**: H2 (mechanical acceptance)
- **Evidence**: Maintainer-reported issue, clear reproduction case
- **Root Cause**: No validation of contrast vector, returns NaN when all zeros
- **Fix**: Add validation in test_contrasts to raise ValueError for zero contrasts
- **Test**: Added regression test for zero contrast detection
- **Confidence**: High - maintainer issue, clear improvement

### #883 - run_hmc error with JAX PRNGKey (FIXED)
- **Type**: Bug (partial - only fixed run_hmc, not sign issue)
- **Status**: Queued for PR
- **Branch**: fix-run-hmc-jax-key-883
- **Hypothesis**: H2 (mechanical acceptance)
- **Evidence**: Clear traceback showing JAX key incompatibility with numpy
- **Root Cause**: JAX PRNGKey passed to numpy.random.default_rng which doesn't accept JAX objects
- **Fix**: Convert JAX PRNGKey to integer seed before passing to numpy
- **Test**: Added regression test for run_hmc with rng_key
- **Confidence**: High - clear type error, simple conversion

## Rejected Issues

### #963, #962, #961 - CI test failures on Python 3.14/3.12
- **Reason**: Maintainer cannot reproduce (comment on #963)
- **Type**: Flaky CI or environment-specific
- **Not actionable**: Cannot reproduce locally

### #881 - assign_mixture_model is slow with JAX/CUDA
- **Reason**: Performance issue, assigned, 8 comments, needs profiling
- **Not actionable**: Not a simple bug fix, requires optimization work

### #777 - MLP convergence issues
- **Reason**: Statsmodels convergence warnings, data-dependent
- **Not actionable**: Likely parameter tuning or model specification issue

### #766 - Inconsistent covariate formatting
- **Reason**: Assigned to maintainer, 6 comments, API design question
- **Not actionable**: Needs maintainer decision on which format to standardize

## Repository Patterns

- **Maintainer**: Lukas Heumos (Zethson) is active, merges bug fixes quickly
- **Test Coverage**: Good - existing test suite for CODA, DGE modules
- **Code Quality**: High - type hints, docstrings, pre-commit hooks
- **PR Style**: Small, focused fixes preferred (recent "Fix minor bugs" PR)
- **Review Speed**: Fast - PRs merge within days when CI passes

## Standing Strategy

1. Fix mechanical bugs first (plotting, validation, type compatibility)
2. Add regression tests for all fixes
3. Keep PRs small and focused (one issue per PR)
4. Follow existing code patterns (error messages, validation style)
5. Build trust through quality fixes before tackling design issues

## Next Steps

- Push all 4 branches
- Create PRs from queued branches
- Monitor CI and respond to review comments quickly
- After 1-2 merges, consider tackling assigned issues (#766, #881)
