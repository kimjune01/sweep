# pallets/jinja triage graph

Scanned: 2026-05-09
Stars: 11.6K | Open bugs: ~9 | External merge rate: ~35%
Standing transfer: same org (pallets) and maintainer (davidism) as click PR #3414.

## Picked

### #2118 — slice returns extra item when count divides length evenly (BUG)
- **Branch**: `fix-slice-fill-even-divisible`
- **Status**: committed, pushed, ready to PR via drip
- **Root cause**: `slices_with_extra == 0` makes `slice_number >= slices_with_extra` always true, so `fill_with` is appended to every slice even when no slice is shorter.
- **Fix**: add `slices_with_extra` truthiness guard to the condition.
- **Tests**: 912/912 pass. Added `test_slice_fill_with_even_divisible`.
- **Competing PRs**: 7 closed, all bot-generated, zero maintainer reviews. Clean lane.
- **Confidence**: high. Mechanical bug, one-line fix, clear acceptance criteria from issue.

## Evaluated and passed

### #2069 — meta.find_undeclared_variables regression in 3.1.5
- Regression introduced by PR #1665. Variables set in all if/elif/else branches are reported as undeclared.
- davidism: "happy to review a PR." 5 thumbs up across comments.
- No competing PRs.
- **Why passed**: requires understanding the visitor pattern in `meta.py` deeply. The bug is in how `TrackingCodeGenerator` handles branched `set` statements. Higher complexity, but a strong second pick. Also, third-party commenter (sjrl) notes the bug exists in 3.1.4 for if/else without elif, so the fix scope is larger than the issue states.

### #2108 — include without context doesn't work in macro
- PR #2161 already open, zero reviews. Would be competing.
- **Why passed**: competing PR exists.

### #2109 — poor perf parsing unclosed strings with many escapes
- Regex performance in lexer. PR #2164 was closed (bot-generated).
- aledelaoo expressed interest in comments.
- **Why passed**: regex optimization is complex, unclear scope, someone else expressed interest.

### #2165 — map(attribute, default=None) fails on empty dicts
- Zero comments, filed 5 days ago. Too fresh, no maintainer signal.

### #2145 / #2079 — test_elif_deep RecursionError on s390x
- Platform-specific (s390x). PR #2146 open (lowers depth from 1000 to 100).
- **Why passed**: competing PR, platform we can't test.

### #2092 — SyntaxErrors during fuzzing
- davidism: "turning Python SyntaxError into TemplateSyntaxError makes sense."
- No competing PRs. Viable second pick but requires fuzzing infrastructure.

### #2120 — missing type annotation for FILTERS
- PR #2141 open (type annotation). Community member offered, maintainer approved.
- **Why passed**: competing PR from community member who was explicitly invited.
