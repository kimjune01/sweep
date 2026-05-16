# Triage Graph: withastro/astro

**Scan date:** 2026-05-08
**Author filter:** kimjune01
**Mode:** dry-run (no remote side effects)

---

## Scan Table

| # | Repo | Type | Title | State | Actionability | Next step |
|---|------|------|-------|-------|---------------|-----------|
| 1 | withastro/astro | PR #16634 | fix(build): strip client:only imports from prerender Rollup graph | CLOSED (not merged) | 2/10 | None -- superseded by compiler PR |
| 2 | withastro/compiler | PR #1162 | fix: strip dead imports for client:only components | OPEN | 8/10 | Unblock CI, add changeset, request review |

---

## Item 1: withastro/astro PR #16634

**State:** Closed (not merged), 2026-05-07
**CI:** All green except 1 integration test failure (pre-existing, unrelated)
**Reviews:** None requested, none received
**Maintainer feedback:** None

### Summary

Vite plugin approach to strip dead `client:only` imports during prerender. Demonstrated a 49% prerender time reduction on a 906-page site with 2,055 client:only React islands. Author self-closed within 20 minutes of opening, citing edge cases (mixed imports, side effects) that are better handled at the compiler level.

### Closing comment (kimjune01)

> "Closing in favor of a compiler-level fix in withastro/compiler. The Vite plugin approach had edge cases (mixed imports, side effects) that are better handled at the source. Will open a PR there instead."

### Actionability: 2/10

This item is **done**. It served its purpose as the prototype that validated the approach and produced the benchmark data now cited in the compiler PR. No action needed unless the compiler PR is rejected and the Vite plugin approach needs to be revisited.

---

## Item 2: withastro/compiler PR #1162

**State:** Open, 2026-05-07
**CI:** `action_required` on all 3 workflow runs -- first-time contributor gate, needs maintainer approval to run CI
**Reviews:** None requested, none received
**Labels:** None
**Changeset:** Missing (changeset-bot flagged it)
**Files changed:** 11 (63 lines added to `print-to-js.go`, 27 lines of new tests, 6 snapshot updates, 3 new snapshots)

### Summary

Compiler-level fix that strips dead imports for `client:only` components during code generation in `print-to-js.go`. Before printing hoisted imports, builds a set of specifiers exclusive to `ClientOnlyComponents`, then skips single-binding, non-type, non-side-effect imports matching that set. Three guard conditions prevent incorrect removal:

1. Mixed imports preserved (`len(stmt.Imports) == 1` guard)
2. Side-effect imports preserved (`len(stmt.Imports) == 0` not matched)
3. Dual-use components preserved (specifier removed from skip set if also in HydratedComponents/ServerComponents)

Known limitation acknowledged: if frontmatter references the imported binding for non-component purposes (e.g. `const Alias = Repl`), import would be incorrectly removed. Author notes this is unlikely for `client:only` components.

### Blockers

1. **CI not running.** All 3 workflow runs show `action_required` -- the withastro/compiler repo requires maintainer approval for first-time contributor CI. No test results available.
2. **Missing changeset.** The changeset-bot flagged the PR. A changeset file is needed for versioning.
3. **No reviewer assigned.** PR has zero reviews, zero review requests, no labels, no milestone.

### Actionability: 8/10

This is the active item. The fix is clean, well-scoped, and has strong benchmarks. But it's stalled on process gates:

**Recommended next steps (in order):**

1. **Add a changeset** -- click the changeset-bot link or create `.changeset/strip-client-only-imports.md` with the patch bump
2. **Request a review** -- tag a compiler maintainer (likely @natemoo-re or @matthewp based on compiler repo history) to approve CI and review
3. **Wait for CI approval** -- once a maintainer approves the workflow, CI will run; if tests pass, the PR is review-ready
4. **Address known limitation** -- if maintainers raise the frontmatter binding edge case, consider adding a binding usage check or documenting it as a known non-goal

---

## Cross-references

| From | To | Relationship |
|------|----|--------------|
| compiler PR #1162 | astro PR #16634 | Supersedes (same fix, different layer) |
| astro PR #16634 body | compiler PR #1162 | References as motivation for closing |
| compiler PR #1162 body | astro PR #16634 | References as prior Vite plugin attempt |

No related open issues found in withastro/astro for `client:only import prerender`. The performance problem is not tracked as a standalone issue -- it was discovered during the user's own site build and went straight to PR.

---

## Recommendations

**Primary:** Focus on unblocking compiler PR #1162. The code is ready; the bottleneck is process (changeset + maintainer CI approval + review request). A single message to a compiler maintainer requesting CI approval and review would move this forward.

**Secondary:** Consider opening a tracking issue in withastro/astro or withastro/compiler documenting the `client:only` prerender performance problem with the benchmark data. This gives maintainers context even if the PR sits in queue, and creates a reference point if the approach needs to change.

**No action needed** on astro PR #16634. It's properly closed with a clear redirect to the compiler PR.
