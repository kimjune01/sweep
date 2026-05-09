# RETRO_GRAPH: python/mypy

Status: **pre-registration** (no own outcomes yet)

## Prior art

### Merge patterns (recent 15)
Tight core team: JukkaL (~60%), ilevkivskyi (~20%), AA-Turner (~13%). One external merge: p-sawicki (#21419, mypyc compilation order, 85+/5-). No first-timer merges in error-message territory.

### Rejection patterns
Hrk84ya (#21436) closed without merge — duplicate of ilevkivskyi's #21435 which landed instead. Pattern: core team races externals on bug fixes.

### Issue #8603 history
Open since April 2020. 37+ thumbs-up. High-profile pain (Flask-SQLAlchemy `db.Model`). JelleZijlstra (member) explicitly invited a PR in 2020: "We'd be likely to accept a PR that improves the error message." Three people asked to be assigned; none completed. PrasanthChettri attempted, got stuck on semanal internals, no further progress.

### Base rates
- External merge rate: 1/15 (p-sawicki, mypyc subsystem).
- Error-message-fix external success: 0 attempts completed.
- Median merged PR size: ~30 lines (excluding mypyc bulk).

## Pre-registration: #8603 (bad error message)

**Target:** Change "Name 'b.a' is not defined" to "object member cannot be used as base class" when base class is an attribute access expression.
**Scope:** ~20 lines Python in `mypy/semanal.py` or `mypy/semanal_main.py`.
**Endorsement:** JelleZijlstra (member) explicitly invited the PR.

### Predictions

| Hyp | Prediction | Falsified if |
|-----|-----------|--------------|
| H0: size gates merge | <30 lines merged; exact wording negotiated in review | Requires >50 lines or architectural change |
| H1: 6-year staleness is signal | Maintainers still accept despite age; issue is "good first issue" shaped | Closed as wontfix or superseded |
| H2: semanal complexity blocks | Previous contributor got stuck; patch must avoid semanal refactoring | Requires touching type inference logic |
| H3: core team race risk | Must land before a core member picks it up | ilevkivskyi or JukkaL ships fix first |
| H4: member endorsement holds | JelleZijlstra's 2020 invitation still valid in 2026 | Rejected by different maintainer overriding endorsement |
| H5: Flask-SQLAlchemy pressure helps | Community pain creates merge pressure | Maintainer explicitly scopes to message-only, rejecting behavioral fix |
| H6: test is mandatory | Must add test case reproducing the bad message | Merged without test |

### Falsification protocol
Submit error-message-only patch + test. Track: time-to-first-response, reviewer identity (JelleZijlstra vs other), wording negotiation rounds. If rejected, classify: complexity (H2), staleness (H1), race (H3), or scope dispute (H5).
