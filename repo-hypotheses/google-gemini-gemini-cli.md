# Triage Graph: google-gemini/gemini-cli (kimjune01)

**Scan date:** 2026-05-08
**Mode:** dry-run (no remote side effects)

## Scan Table

| # | Title | State | Age | Reviews | CI | Score |
|---|-------|-------|-----|---------|-----|-------|
| 24736 | feat(core): union-find context compaction for AgentHistoryProvider | OPEN | ~2w | 19 (all COMMENTED) | CLA signed, docs neutral | **7/10** |

## Scoring Rubric

- **Code quality (2/3):** Large PR (multi-file). Community says "reasonable and interesting approach." Needs refactor to fit new ContextProcessor pipeline.
- **PR quality (3/3):** Active engagement, 24 comments, iterating on feedback.
- **Actionability (2/4):** Needs rebase, needs refactor to ContextProcessor pattern, needs maintainer with merge powers to approve. Community LGTM achieved.

## Current State

### Blockers

1. **Needs rebase** — reviewer explicitly said "needs rebase."
2. **Architecture alignment** — kimjune01 committed to moving union-find clustering into a `ContextProcessor` in the new pipeline (comment from May 8). This is a non-trivial refactor.
3. **Maintainer approval** — community LGTMs don't merge. Need maintainer (with "powers") to approve. Reviewer said "letting maintainers with powers chime in in the next few days."

### PR history

- **#23341** (MERGED) — fix: decode Uint8Array and multi-byte UTF-8 in API error messages. Establishes contributor trust.
- **#23347** (CLOSED) — fix: synchronous stderr write before exit.
- **#23343** (CLOSED) — fix: vim escape during streaming.
- **#23066** (CLOSED) — fix: token accounting and temp file leak.

Merge rate: 1/5 (20%). Higher than tinygrad (7.1%).

## Actionable Issues (discovered 2026-05-09)

Maintainer-labeled help-wanted/good-first-issue bugs, unassigned. 2-4 reviews per merge — deep review culture.

| # | Title | Score | Effort | Labels |
|---|-------|-------|--------|--------|
| 25693 | Skills discovery fails when SKILL.md description is single line | 6 | Small | help wanted, good first issue |
| 25689 | text.response in custom theme triggers validation error | 6 | Small | help wanted, good first issue |
| 25459 | Shell tool text output causes UI jank on high-volume commands | 5 | Medium | help wanted |
| 25458 | Strict auth consent throws opaque error due to startup race | 5 | Medium | help wanted |

**Strategy:** #25693 and #25689 are quick wins — small, clear bugs, high merge probability. Submit these to build merge count while #24736 is in review. One at a time via drip.

## Recommended Next Actions

1. **Rebase #24736 onto main** — immediate, mechanical.
2. **Refactor to ContextProcessor** — the committed architecture change. Do this before pinging again.
3. **Wait for maintainer** — reviewer said "next few days." Don't ping until ~May 14.
4. **Pick up #25693 or #25689** — small wins while waiting. Builds trust for #24736 merge.

---

*Dry run — no remote side effects.*
