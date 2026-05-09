# Triage Graph: withastro/compiler (kimjune01)

**Scan date:** 2026-05-08
**Mode:** dry-run (no remote side effects)
**Scope:** PRs authored by kimjune01, limit 2

## Scan Table

| # | Title | State | Age | Reviews | CI | Changeset | Score |
|---|-------|-------|-----|---------|-----|-----------|-------|
| 1162 | fix: strip dead imports for client:only components | OPEN | 2d | 0 reviews | Blocked (awaiting maintainer approval) | Added | **9/10** |

Only 1 item found for this author. No second item to score.

## Scoring Rubric

- **Code quality (3/3):** 241 additions, 6 deletions. Go implementation in `print-to-js.go` with 3 new snapshot tests and 6 updated snapshots. Clear safety guards (single-binding, non-type, non-side-effect, non-dual-use). Well-documented known limitation.
- **PR quality (3/3):** Thorough body with before/after, measured impact (49% prerender improvement on 906-page site), safety argument, and lineage from the closed Astro PR.
- **Actionability (2/4):** Two blockers remain (changeset + CI approval), both fixable by the author or maintainer respectively. No review engagement yet.

## Blockers on PR #1162

### 1. ~~Missing changeset~~ RESOLVED

Changeset added. Bot now reports "Changeset detected" (patch for `@astrojs/compiler`). Commit `3cff70d`.

### 2. CI requires maintainer approval (not author-fixable)

All 3 CI runs show `conclusion: action_required` with 0 jobs executed. This is GitHub Actions' first-time contributor gate -- a maintainer must click "Approve and run" on the Actions tab. The PR's commit status shows `pending` with 0 statuses. Until a maintainer approves the workflow run, CI results are invisible.

### 3. No reviewer assigned (not author-fixable, but nudgeable)

Zero reviews, zero reviewer assignments. The repo's active maintainers based on recent merges:

- **matthewp** (Matthew Phillips) -- merged #1153, pinged on #1156
- **Princesseuh** (Erika) -- merged #1161, #1156, responds to pings

The external contributor on #1156 (seroperson) had to ping maintainers 3 times over ~5 weeks before getting review. This is a slow-review repo. The PR is 1 day old, so no ping is warranted yet.

## Cross-reference: withastro/astro PR #16634

| Field | Value |
|-------|-------|
| Title | fix(build): strip client:only imports from prerender Rollup graph |
| State | CLOSED (not merged) |
| Author | kimjune01 |
| Closed | 2026-05-07 |
| Reason | Self-closed: "Closing in favor of a compiler-level fix in withastro/compiler. The Vite plugin approach had edge cases (mixed imports, side effects) that are better handled at the source." |

The Astro PR was a Vite plugin approach. Compiler PR #1162 is the replacement, fixing the same problem at the compiler level. The PR body in #1162 explicitly references #16634 for lineage. Clean handoff.

## Actionable Issues (discovered 2026-05-09)

Maintainer-engaged bugs in this repo, unassigned. Sorted by signal strength.

| # | Title | Priority | Maintainer signal | Adjacent to #1162? |
|---|-------|----------|-------------------|-------------------|
| 1091 | Backslash in tag attribute value is escaped | — | MoustaphaDev gave exact file+line (`printer.go#L474`) | No (printer path) |
| 1139 | Server islands doesn't work with Astro.self | — | matthewp + Fryuni agreed to special-case in import tracker | Yes — same import-tracking code |
| 1096 | Nested lists wrong order with slots | P4 | delucis confirmed compiler bug with playground repro | No (HTML parser) |
| 1116 | Conditional branching in `<td>` causes DOM corruption | P3 | Maintainer-engaged, related to #958 and #1015 | No (HTML parser) |
| 1068 | Whitespace preserved after style is moved | P3 | natemoo-re acknowledged as real bug | No (printer) |

**Strategy:** #1139 is the natural next PR after #1162 lands (same code path). #1091 is the lowest-effort standalone fix (exact code reference given). The HTML parser bugs (#1096, #1116) are a batch — same subsystem.

## Recommended Next Actions

### Immediate (author)

1. ~~Add the changeset~~ DONE. Changeset added, bot confirms.

### Wait (1 week from open)

2. **Ping maintainers.** If no review by ~May 14, leave a comment tagging `@matthewp` or `@Princesseuh`. Precedent: seroperson pinged weekly on #1156 and eventually got merged.

### After #1162 lands

3. **Pick up #1139** (Astro.self server islands) — natural extension of import-tracking work.
4. **Pick up #1091** (backslash escaping) — small standalone fix, builds merge history.

### Do not do

- Do not re-target to `next` branch. The changeset config references `baseBranch: "next"` but that branch does not exist. All 5 recent merges target `main`. The config is stale.
- Do not open an issue. The PR body is thorough enough to serve as the issue. The Astro PR provides additional context.
