# Hypothesis graph: pymc-devs/pymc#8285

Reinvestigate cycle. PR `fix/discrete-float-observed-warning` at SHA `10fcb80356d2` is MERGEABLE but CI red.

## H₀: CI red because PR broke timeseries

- Observation: `ubuntu (numba, 3.14, ...)` and the aggregator `all_tests` both FAILURE.
- Direct perturbation: extract the failing test from the full log.
- Result: **single failure** is `tests/distributions/test_timeseries.py::TestGARCH11::test_batched_size[False-alpha_1]` at line 787 — `assert not np.any(np.isclose(y_eval[0], y_eval[1]))`. `all_tests` is just an aggregator that mirrors that single failing job.
- Classification: **divergent against**. The PR diff touches only `pymc/model/core.py` and `tests/model/test_core.py`. No path from those edits to GARCH11 sample equality.
- Killed.

## H₁: Test is intrinsically flaky

- Reading `tests/distributions/test_timeseries.py:767-787`:
  - Line 769: `param_val = np.square(np.random.randn(batch_size))` — **uses unseeded numpy global RNG**.
  - Line 785: `draw(y, draws=2, random_seed=800)` — draws are seeded, but the *parameter values* fed into GARCH11 are not.
  - Line 787 asserts the two draws are not pointwise close. Whether the assertion holds depends on `param_val`, which varies per CI run.
- Perturbation: search master CI for the same failure.
- Result: master is mostly green; one recent main failure (`25765219868`) failed on an unrelated `test_plot_gp_dist_warn_nan` (Windows tk). The specific GARCH11 test passes on master — but that just means the unseeded RNG hasn't tripped it there recently. The mechanism is intact.
- Classification: **convergent**. The test contains a real bug (unseeded RNG); our PR cannot have caused it; we observed the rare case.
- Confirmed (abduction → deduction via source read; ~90%).

## H₂: Patching the test is the right action

- Options for this PR:
  - (a) Rerun the failing job — fast, no diff, but the same flake can recur.
  - (b) Patch the test to seed `np.random` — out of scope for `fix/discrete-float-observed-warning`; "imitate, do not reform."
  - (c) Push an empty commit and let CI rerun.
- Decision: **(a) rerun**. The PR title is about TypeError on discrete float observed data; modifying an unrelated timeseries test would be scope creep that triggers reviewer pushback. The user-facing tests for this PR (`test_discrete_float_observed_*`) all passed in the failing run (lines 79-82 of the context pack).

## Frontier

- If the rerun goes red on the same test → file it upstream as a flaky-test report (separate concern); leave the PR alone, wait for review.
- If the rerun stays red on a different test → re-enter Phase 2.

## Reasoning modes

- H₀ killed by deduction (read the PR diff, no causal path to GARCH11).
- H₁ confirmed by deduction (read line 769, unseeded RNG).
- H₂ is policy ("imitate, do not reform").

## Action

Rerun the failed CI jobs on this PR. No code changes.

---

## Cycle 2 (2026-05-19)

Re-fetched the failed-log on the same head SHA `10fcb80356d2`. Same single failure: `TestGARCH11::test_batched_size[False-alpha_1]` with `assert not np.True_` — exactly one coincidence in a (5,100) `isclose` matrix. PR-added tests still PASSED in the same job. Diagnosis from cycle 1 stands: pre-existing flake driven by the unseeded `np.random.randn` at `tests/distributions/test_timeseries.py:769`.

PR state is REVIEW_REQUIRED + MERGEABLE — the gate is reviewer attention, not CI. **Fixed-point reached** (three consecutive iterations would produce this same diagnosis). Halt; no readiness record written, no patch to push.
