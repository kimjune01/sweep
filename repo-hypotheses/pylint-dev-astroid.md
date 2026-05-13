# pylint-dev/astroid Triage Graph

Repo: pylint-dev/astroid (575 stars, Python AST inference for pylint)
Triage date: 2026-05-09
Org status: pylint-dev/pylint#11002 open, org-blocked for push

## Selected: #2646 - AttributeError crash in starred_assigned_stmts

- **Type:** Crash (Needs PR)
- **Labels:** Crash, Needs PR
- **Root cause:** `_determine_starred_iteration_lookups` in `astroid/protocols.py` compares starred nodes via `.value.name`, which only exists on `Name`/`AssignName` nodes. `AssignAttr` (e.g. `*o.attr`) and `Subscript` (e.g. `*d[0]`) lack `.name`.
- **Fix:** Replace name comparison with node identity (`element is starred`). Strictly more correct -- also fixes same-name ambiguity in `*a, (*a,)`.
- **Branch:** `fix-starred-assignattr-crash` (3 commits, pushed to fork)
- **Tests:** 466 passed, 0 failures. 3 new regression tests added (AssignAttr, Subscript, same-name identity).
- **Codex review:** Approved. Strengthened tests per feedback (both starred nodes, same-name case).
- **Gemini review:** Approved. Added Subscript test per feedback.
- **Status:** Ready to PR when org unblocked.

## Considered and rejected

### #2864 - pathlib.Path.parents brain variable assignment
- Labels: Bug, Brain, Needs PR
- **Rejected:** Already assigned to SK8-infi with maintainer blessing. Competing.

### #2632 - Incorrect inference of decorated function
- Labels: Needs PR, decorators
- High complexity: requires understanding decorator inference chain. Good H2 candidate if #2646 lands.

### #2668 - Incorrect removal of brackets (walrus as_string)
- No labels
- **Rejected:** Already addressed by PR #3045 (SAY-5).

### #3007 - Remove asname argument from ImportNodes._infer
- Labels: Help wanted
- Low risk refactor, good trust-building follow-up.

### #2075 - aiohttp.ClientSession crashes pylint
- Labels: Crash, Needs PR
- Complex brain issue, 8 comments of discussion. Higher effort.

## Competing PR landscape

| PR | Title | Status | Conflict? |
|----|-------|--------|-----------|
| #3047 | Python 3.15 KW_ONLY + namespace | REVIEW_REQUIRED | No |
| #3046 | GObject introspection exact signatures | REVIEW_REQUIRED | No |
| #3045 | Walrus parens in as_string | REVIEW_REQUIRED | Covers #2668 |
| #3031 | Annotated Ellipsis assignments | REVIEW_REQUIRED | No |
| #2995 | str(const) inference | CHANGES_REQUESTED | No |
| #2977 | And/Or constraints | REVIEW_REQUIRED | No |
| #2965 | Decorated FunctionDef return | REVIEW_REQUIRED | No |
| #2710 | numpy <3 dependency | Needs take over | No |
| #2531 | Module discovery order | REVIEW_REQUIRED | No |

## Next actions

1. Wait for pylint-dev/pylint#11002 to close/merge
2. Open PR for #2646 referencing the issue
3. If landed: pursue #3007 (help-wanted refactor) or #2632 (decorated function inference)
