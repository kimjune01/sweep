# Triage Graph: pymc-devs/pymc

Repo: https://github.com/pymc-devs/pymc (9.6K stars, probabilistic programming)
Triaged: 2026-05-09
Branch: fix/discrete-float-observed-warning

## Target Issue

### #8282 - BUG: Discrete distributions silently cast float observed values to integers [SELECTED]
- **Status:** Open, no competing PRs
- **Maintainer signal:** ricardoV94 (MEMBER) said "Sounds reasonable"
- **Community:** Thematiq offered to contribute but no PR opened
- **Fix:** Validate float-to-integer casts in `make_obs_var()`, raise TypeError when values would be altered
- **Files changed:** `pymc/model/core.py`, `tests/model/test_core.py`
- **Review:** Codex pass (after narrowing scope), Gemini pass (after adding sparse handling)
- **Tests:** 128/128 existing tests pass, 4 new regression tests added

## Evaluated and Rejected

### #8106 - Deprecation warning from cachetools v7 [SKIP]
- Labels: help wanted, dependencies
- Competing PR: #8115 (open)
- Maintainer (ricardoV94): "No we don't want to implement it ourselves. Pinning it until we refactor VI is fine"
- **Reason:** Maintainer explicitly rejected the fix approach

### #8091 - update_node_formatters rejects documented string keys [SKIP]
- Labels: bug
- Competing PRs: #8118, #8212, #8218 (THREE open PRs)
- **Reason:** Extremely crowded, three competing implementations

### #8132 - BaseHMCState instances not __eq__ comparable [SKIP]
- Labels: bug
- Competing PR: #8134 (open, has reviews)
- **Reason:** Already claimed with active PR

### #8213 - BaseHMC doesn't pass dtype to QuadPotentialDiagAdapt [SKIP]
- Labels: bug
- Competing PR: #8280 (open, maintainer asked to run pre-commit)
- **Reason:** Already claimed with active PR

### #8219 - vectorize_over_posterior crashes with ZeroSumNormal [SKIP]
- Labels: bug
- **Reason:** Already fixed via merged PR #8220

### #8173 - freeze_dims_and_data breaks HalfStudentT logp [SKIP]
- Labels: bug
- **Reason:** Already fixed via merged PR #8174

### #8169 - TestPopulationSamplers started failing in CI [SKIP]
- Labels: bug, help wanted, GitHub CI/CD
- Competing: Two people claimed in comments
- **Reason:** CI-specific, already claimed

### #8104 - ZarrTrace unnecessarily loads all data into memory [SKIP]
- Labels: bug
- Related PR: #7687 (different scope)
- **Reason:** Complex refactor, PR already in progress on related work

### #8077 - to_graphviz breaks with CustomDist [SKIP]
- Labels: bug
- Competing PRs: #8078, #8092
- **Reason:** Two competing PRs

### #8024 - model_to_graphviz fails with Flat variables [SKIP]
- Labels: bug
- Competing PRs: #8062, #8033
- **Reason:** Two competing PRs

### #7628 - CategoricalGibbsMetropolis KeyError 'diverging' [SKIP]
- Labels: bug
- **Reason:** Already fixed on main (commit 977ecaa98, PR #8015 removed tune stat)

### #7460 - target_accept can be larger than 1 [SKIP]
- Labels: bug
- Competing PR: #8158 (open)
- **Reason:** Already claimed

### #7429 - Debug message for scalar values fails [SKIP]
- Labels: bug
- Competing PR: #8103 (open, has reviews)
- **Reason:** Already claimed with active PR

### #6966 - model.debug doesn't work with Potentials [SKIP]
- Labels: bug
- Competing PR: #8159 (open)
- **Reason:** Already claimed

## Repo Culture Notes

- **Active maintainer:** ricardoV94 reviews most PRs, responsive within 1-2 days
- **High AI PR density:** Many issues have 2-3 competing PRs from drive-by contributors
- **Bug fixes land:** Focused bug fixes with tests get reviewed quickly
- **Feature requests stall:** help-wanted features from 2022-2023 remain open
- **Pre-commit required:** ricardoV94 explicitly asks for pre-commit compliance
- **Test coverage enforced:** Codecov bot comments on every PR
