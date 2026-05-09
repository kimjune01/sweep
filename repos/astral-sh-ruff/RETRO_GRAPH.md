# RETRO_GRAPH: astral-sh/ruff

Status: **pre-registration** (no own outcomes yet)

## Prior art

### Merge patterns (recent 15)
Core team dominates: MichaReiser, charliermarsh own ~80% of merges. dylwil3 is a trusted collaborator (small, targeted fixes). Bots (renovate) handle deps. Zero first-time external contributor merges in sample.

### Rejection patterns
TD003 regex fix (#16519) has 4 failed external PRs: #24774 (multi-fix bundle, closed), #24260 (closed), #24156 (closed), #23101 (closed). Pattern: externals scope too broadly or bundle unrelated changes.

### AI policy
PR #24198 merged: AI policy added to PR template. Signals active screening.

### Base rates
- External merge rate: ~1/15 (dylwil3, who is a collaborator). True first-timer: 0/15.
- TD003 external success rate: 0/4 attempts.
- Median merged PR size: ~30 lines (non-bot).

## Pre-registration: #16519 (TD003 regex)

**Target:** Fix regex in `flake8-todos` TD003 to match `FOOBAR-1234` on same line as TODO.
**Scope:** ~5 lines Rust, single regex change + test.
**Endorsement:** dylwil3 (collaborator) acknowledged the issue.

### Predictions

| Hyp | Prediction | Falsified if |
|-----|-----------|--------------|
| H0: size gates merge | <10 lines merged in <7 days | >50 lines needed or review drags >14 days |
| H1: scope creep kills | Single-file PR succeeds; bundled PR fails | Maintainer requests scope expansion |
| H2: test requirement | Must include snapshot test update | Merged without test |
| H3: AI detection active | Must disclose AI per template; clean code passes | Rejected citing AI quality |
| H4: collaborator endorsement lifts | dylwil3's prior engagement accelerates review | Ignored despite endorsement |
| H5: regex-only is safe territory | Behavioral change without API surface risk merges | Rejected as "design decision" |
| H6: prior failures are scope failures | Narrow fix succeeds where bundles failed | Narrow fix also rejected |

### Falsification protocol
Submit single-file regex fix + test. If rejected, classify: scope (H1), quality (H3), design (H5), or gatekeeping (H4). Record time-to-first-response and time-to-resolution.
