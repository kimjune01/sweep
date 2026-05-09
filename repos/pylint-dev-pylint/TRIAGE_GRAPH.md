# pylint-dev/pylint Triage Graph

Repo: pylint-dev/pylint (5.7K stars, PyCQA ecosystem)
Triage date: 2026-05-09
Maintainers: Pierre-Sassoulas (MEMBER), jacobtylerwalls (MEMBER)

## Candidates Scored

### Selected: #8785 — Use inference to determine if **kwargs is missing a named parameter
- **Type**: False Negative (bug fix)
- **Labels**: Good first issue, False Negative, Hacktoberfest, Needs PR
- **Opened by**: jacobtylerwalls (maintainer)
- **Competing PRs**: None
- **Maintainer pointer**: Exact lines 1616-1622 in typecheck.py identified
- **Score**: HIGH — maintainer-opened, exact fix location given, no competition, bug fix (merges)
- **Status**: COMMITTED on `fix-8785-kwargs-no-value-for-parameter`

### Rejected Candidates

| # | Title | Reason |
|---|-------|--------|
| 10476 | Return value of None-returning function | Needs specification lock, assigned contributor |
| 10281 | use-implicit-booleaness-not-len expansion | Needs decision lock, 24 comments (bikeshed) |
| 10092 | invalid-envvar-default for os.environ.get | Competing PR #10507 (open since Aug 2025) |
| 9833 | Dynamic __getattr__ + no-member | Requires astroid constraint (deep work), reporter claimed it |
| 9692 | NoReturn method discovery | Good candidate, held in reserve. UnboundMethod fix needed. |
| 9598 | assertDoesNotAddMessages | Competing PR #10930 |
| 9317 | unnecessary-lambda docs | Assigned to contributor, Needs investigation |
| 9143 | JUnit reporter | Two competing PRs (#10985, #11001) |
| 9063 | Test suite randomization | Low visibility infra work |

## Fix Details

**Root cause**: In `typecheck.py` step 3 (Match **kwargs), when `node.kwargs` is truthy, all remaining parameters are blindly marked as assigned. But `CallSite._unpack_keywords` already extracts dict literal keys into `keyword_arguments`, which are matched in step 2. Step 3 then masks the missing parameter.

**Fix**: Gate step 3 on `has_no_context_keywords_variadic` — only assume kwargs covers all params when the kwargs are genuinely uninferrable (function scope passes through `**kwargs` without context). When kwargs are inferable (dict literals), they were already handled in step 2.

**Key insight**: By the time step 3 is reached, `has_invalid_keywords()` is always False (early return at line 1490-1492), so all kwargs have been fully unpacked. Step 3 was purely redundant masking.

## Next Candidates (Priority Order)

1. **#9692** — NoReturn method discovery (inconsistent-return-statements false positive)
2. **#8785** follow-ups if maintainer requests changes
3. **#9063** — Test randomization (low effort, good relationship builder)
