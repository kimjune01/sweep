# Triage Graph: nicklockwood/SwiftFormat

## Repo context
- PRs target **develop** branch (not main)
- AGENTS.md present: no AI names in file headers, use Formatter APIs, no raw index loops
- CONTRIBUTING.md: semver, bug fixes against develop, tests required
- No anti-AI policy detected

## Completed

### #1415 — `redundantParens` rule not removing redundant parens in return statement
- **Status**: qa_passed, in drip queue
- **Branch**: fix/redundant-parens-try-optional
- **Type**: bug fix (maintainer-acknowledged)
- **Labels**: bug, partly resolved
- **Fix**: The `?`/`!` in `try?`/`try!` was treated as an unwrap operator, blocking paren removal. Added `nonTryUnwrapOperatorIndex` helper to skip unwrap operators immediately following `try`.
- **Tests**: 3 new test cases (try? in return, try! in return, try? with operator preserved)
- **Risk**: Low — targeted fix, no regressions on existing behavior

## Candidates (not yet triaged)

### #2509 — `sortImports` removes code inside #if #elseif #endif code blocks
- **Type**: bug
- **Complexity**: High — sort logic with preprocessor conditionals
- **Comments**: 0
- **Assessment**: Likely a significant bug in sort boundary detection. Needs investigation.

### #2442 — indentCase option doesn't handle case pattern wrapping properly
- **Type**: bug
- **Complexity**: High — deeply coupled indentation logic
- **Comments**: 0, no maintainer response
- **Assessment**: Indentation rules are complex. Maintainer hasn't acknowledged. Skip for now.

### #2524 — `hoistAwait` removes `await` from async autoclosure argument
- **Type**: unlabeled, likely bug
- **Complexity**: Medium
- **Comments**: 0
- **Assessment**: Potential semantic-changing bug. Needs investigation.

## Denied

(none)
