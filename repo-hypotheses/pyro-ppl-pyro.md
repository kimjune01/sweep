# pyro-ppl/pyro Triage Graph

Last updated: 2026-05-09

## Repo Profile

- Stars: ~9K. Python probabilistic programming library (PyTorch-based).
- Org: pyro-ppl (same org as NumPyro where we have PR #2188).
- Activity: moderate. 30 open PRs, many stale (2020-2022 era). Recent merges include maintainer PRs and external bug fixes.
- Maintainers: eb8680 (active, responds to issues), fritzo, neerajprad, fehiepsi.
- Merge pattern: maintainer PRs merge fast. External PRs: bug fixes merge, features stall.

## Issues Scanned

### Picked: #3407 — Prohibit negative plate sizes [bug fix, help wanted]
- **Status**: COMMITTED on branch `fix-negative-plate-size`
- **Competing PRs**: 0
- **Comments**: 0 (no one has claimed it)
- **Scope**: 4 lines in `SubsampleMessenger._subsample`, 12 lines test
- **Why this one**: Pure bug fix. Zero competition. Maintainer-labeled help-wanted. Negative `size` silently produces incorrect log-likelihood scaling via `size/batch_size`. Existing check catches `size == 0` (ZeroDivisionError) but not negative. Our fix adds ValueError before the `_Subsample` distribution is created.

### Deferred: #2995 — Port NumPyro examples to Pyro [good first issue, help wanted]
- Large scope (3+ tutorials). PR #3006 (Bayesian regression) open since Jan 2022, never merged.
- Multiple people claimed subtasks in comments but no PRs landed.
- Risk: tutorial PRs languish in review. Not a bug fix. Defer until we have merge trust.

### Deferred: #3417 — Add order parameter to spline_coupling [help wanted]
- 4 comments: 3 people asked to work on it, no PR submitted.
- Issue filed by external user, not maintainer. Maintainer hasn't commented.
- Contested (3 claimants). Skip.

### Deferred: #3013 — mcmc.summary() as DataFrame [enhancement, help wanted]
- 6 comments, feature request. No competing PR.
- Enhancement, not bug fix. Needs maintainer design input on API.

### Deferred: #3088 — Incorrect stack terminology [docs, help wanted]
- Documentation fix. Low merge probability for first contribution.

### Watch: #3142 — Allow orthogonal params in pyro.param [good first issue]
- PR #3445 already open (joydipb01). Contested.

### Watch: #2550 — Python type hints [good first issue]
- Massive scope. PR #3367 (partial typing) open since May 2024.

## Cross-pollination with NumPyro
- Our NumPyro PR #2188 is in the same org. If it merges, we gain org-level trust.
- eb8680 is active in both repos (filed #2995, maintains Pyro).

## Next Steps
1. Push #3407 PR via drip queue
2. If #3407 merges: look at #3013 (mcmc.summary as DataFrame) or pick up Bayesian Imputation from #2995
3. Monitor NumPyro PR #2188 for cross-org credibility
