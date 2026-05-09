# RETRO_GRAPH: prometheus/prometheus

Status: **pre-registration** (no own outcomes)

## Prior art (other contributors)

### roidelapluie — core team pattern
- #18650 (MERGED): discovery/stackit use config.Secret
- #18651 (MERGED): web: reject concurrent fgprof profiles
- #18643 (MERGED): ci: restrict govulncheck PR runs
- #18649 (MERGED): discovery/stackit fix

Pattern: roidelapluie is a core team member shipping multiple PRs per week. External contributor merges not in recent sample — core team dominates.

### bwplotka — core team
- #18641 (MERGED): fix: check bounds on remote write receive

## Pre-registration: #16525 (label_value_length_limit)

| Hyp | Prediction | Falsified if |
|-----|-----------|--------------|
| H0 | Issue exists, good-first-issue labeled. Predict: issue-first helps | Rejected despite label |
| H2 | Zero standing, core team dominates merges. Predict: cold start is hard | Merged despite zero standing |
| H5 | CNCF governance, DCO required. Predict: process overhead but fair review | Ignored without review |

## Base rates
- External merge rate: not measured (core team dominates recent sample)
- Good-first-issue: 4 open — suggests willingness to accept external contributions
- CLA/DCO: required (DCO sign-off)
