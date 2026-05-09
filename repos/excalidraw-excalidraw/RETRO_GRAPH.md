# RETRO_GRAPH: excalidraw/excalidraw

Status: **pre-registration** (no own outcomes)

## Prior art (other contributors)

### Recent external merges
- praneethhere #11286 (MERGED): fix duplicate lasso toolbar item
- sznmelvin #11179 (MERGED): fix ctrl+y redo shortcut on linux/mac
- alechulkin #11290 (MERGED): fix app-jotai import path

Pattern: small, self-contained bug fixes by first-time contributors merge. All are `fix()` prefixed. No feature PRs in recent external sample.

| H0 | all 3 are bug fixes, not issue-first | NEUTRAL |
| H1 | all follow fix() conventional commits, small diffs | FOR |
| H2 | all appear to be first-time contributors | AGAINST — no standing gate for small fixes |

## Pre-registration: #9527 (hex color validation)

| Hyp | Prediction | Falsified if |
|-----|-----------|--------------|
| H0 | Issue exists, good-first-issue labeled | Predict: merge |
| H1 | Small UX fix, follows fix() convention | Predict: merge |
| H2 | Zero standing, but repo merges first-timers | Predict: no gate |
| H5 | Small, trivially verifiable | Predict: fast review |

## Base rates
- External merge rate: ~30% (from hypothesis data)
- First-timer merge: observed (3 recent examples)
- Good-first-issue pool: 30 open
