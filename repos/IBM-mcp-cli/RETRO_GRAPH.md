# RETRO_GRAPH: IBM/mcp-cli

Status: **own outcomes** (3 merged PRs)

## Own outcomes

### PR #125 — Fix failing ping tests (MERGED)
| Hypothesis | Evidence | Direction |
|------------|----------|-----------|
| H0 (issue-first) | no linked issue, unsolicited fix | NEUTRAL |
| H2 (standing) | first PR to repo, cold start | AGAINST — merged despite zero standing |
| H5 (efficiency) | title-only PR, no body, 0 reviews | FOR — merged without review |

### PR #126 — Fix failing tests & improve error handling (MERGED)
| Hypothesis | Evidence | Direction |
|------------|----------|-----------|
| H2 (standing) | second PR, 1 day after first | NEUTRAL |
| H5 (efficiency) | title-only, 0 reviews | FOR |

### PR #127 — fix round trip examples (MERGED)
| Hypothesis | Evidence | Direction |
|------------|----------|-----------|
| H2 (standing) | third PR, same day | FOR — standing accumulates |
| H5 (efficiency) | title-only, 1 review | FOR |

## Summary
3/3 merged, all bug fixes, all with minimal descriptions. Repo accepts PRs with zero body text. Standing gate is non-existent for bug fixes. Review is cursory (0-1 reviews).

## Pre-registration: #203 (ping over SSE)

| Hyp | Prediction | Falsified if |
|-----|-----------|--------------|
| H2 | 3 merged PRs = strong standing. Predict: merge in <48h | Ignored despite standing |
| H5 | Repo accepts title-only PRs. Predict: minimal body sufficient | Rejected for insufficient description |

## Base rates
- Own merge rate: 3/3 (100%)
- External merge rate: not measured (small repo)
- Review depth: minimal (0-1 reviews per PR)
