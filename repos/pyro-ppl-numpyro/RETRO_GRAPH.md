# RETRO_GRAPH: pyro-ppl/numpyro

Status: **pre-registration** (no own outcomes)

## Prior art (other contributors)

### Qazalbash — trusted collaborator pattern
- #2185 (MERGED): doc improvement for Beta distribution
- #2085 (MERGED): fix MyPy errors in constraints module
- #2182 (MERGED): fix Poisson.log_prob casting

Pattern: Qazalbash ships 3 PRs (2 fixes, 1 doc) in quick succession. All merged. Collaborator badge. This is the standing-building trajectory the pipeline predicts.

| H0 | doc PR #2185 wasn't issue-first, still merged | AGAINST |
| H2 | Qazalbash earned collaborator status through volume | FOR |
| H5 | doc and small fix PRs merge with minimal review | FOR |

### Other external merges
- ordabayevy #2183 (MERGED): fix HPDI docstring
- jsakv #2184 (MERGED): fix SWIG reference

Both small doc/ref fixes. fehiepsi (maintainer) merges external work readily.

## Pre-registration: #2187 (distribution docs)

| Hyp | Prediction | Falsified if |
|-----|-----------|--------------|
| H0 | Not issue-first, but good-first-issue labeled. Predict: merge | Rejected despite label |
| H2 | Zero standing. But repo merges first-timers (jsakv). Predict: no gate | Rejected citing contributor quality |
| H5 | Doc PR, minimal review burden. Predict: <48h merge | Review drags >7 days |

## Base rates
- External merge rate: ~90% (from retro params)
- First-timer merge: observed (jsakv, ordabayevy)
- Maintainer: fehiepsi, actively mentors
