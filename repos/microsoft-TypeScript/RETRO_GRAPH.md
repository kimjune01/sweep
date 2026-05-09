# RETRO_GRAPH: microsoft/TypeScript

Status: **pre-registration** (no own outcomes yet)

## Prior art

### Merge patterns (recent 15)
Core team only: RyanCavanaugh, jakebailey, typescript-bot, copilot-swe-agent. External: two 1-line doc fixes. Zero external behavioral merges.

### #30408: 7 prior attempts, all failed
| PR | Author | Status | Pattern |
|----|--------|--------|---------|
| #63438 | creazyfrog | closed | label continue/break error |
| #63413 | Jah-yee | closed | invalid continue target |
| #63365 | Ankitajainkuniya | closed | skip block-scoped check for labels |
| #63302 | wdskuki | closed | label error message fix |
| #63256 | AkaHarshit | closed | mislabeled jump targets |
| #62925 | mhughes2012 | closed | string index signature fallback (wrong fix) |
| #54927 | Mvmo | closed | out of scope label message |

Most misdiagnose the issue or change the wrong error path.

### AI policy
AI disclosure required (#63366). Comment automation suppressed (#63412). AGENTS.md gates maintenance mode. Active screening.

### Base rates
- External behavioral merge: 0/15. #30408 success: 0/7 over 6 years. Hardest target of the three.

## Pre-registration: #30408 (label error message)

**Target:** Improve TS1007 error when label is after the jump statement.
**Scope:** ~50 lines in checker + tests.
**Endorsement:** DanielRosenwasser acknowledged. Filed against TS, not TS-go.

### Predictions

| Hyp | Prediction | Falsified if |
|-----|-----------|--------------|
| H0: 0/7 base rate is real | This attempt also fails without maintainer collaboration | Merged on first submission |
| H1: misdiagnosis is the failure mode | Correct diagnostic path (checker label resolution) succeeds where wrong paths failed | Correct path also rejected |
| H2: AI screening blocks | Must pass AI disclosure; clean human-authored code required | Rejected citing AI despite disclosure |
| H3: repo is functionally closed | Only core team + copilot-swe-agent land behavioral changes | External behavioral PR merged |
| H4: DanielRosenwasser endorsement helps | His acknowledgment creates review path | Different maintainer closes without review |
| H5: TypeScript-go redirect | Maintainer redirects to TypeScript-go repo | Accepted in TypeScript repo |
| H6: test burden is high | Must update baselines across multiple test scenarios | Minimal test suffices |

### Falsification protocol
Submit diagnostic-only fix with correct checker path. If rejected, classify: misdiagnosis (H1), closed-repo (H3), redirect (H5), or AI screening (H2). 0/7 base rate makes this the strongest test of prior art analysis.
