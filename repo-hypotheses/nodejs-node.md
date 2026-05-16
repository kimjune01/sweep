# nodejs/node Triage Graph

**Date:** 2026-05-09
**Status:** Active — one PR ready to submit

## Previous monitoring target

### PR #63162 — crypto: runtime-deprecate calling Hmac.digest() more than once (DEP0206)
- **State:** OPEN, CI failing (Linux, macOS, shared libs), REVIEW_REQUIRED
- **Assessment:** Stalled. Multiple CI failures, no recent maintainer engagement.
- **Action:** No longer blocking us — we pivoted to other issues.

## Triage scan results

### Confirmed bugs with competing PRs (blocked)

| Issue | Title | Competing PR | Status |
|-------|-------|-------------|--------|
| #63180 | sqlite: segfault on db.close() from user function | #63183 (mceachen) | CI passing, awaiting review |
| #62897 | fs.glob: early return skipping sibling entries | #62901 (semimikoh) | Open |
| #62693 | test_runner: infinite loop on malformed v8 header | #62704 (thisalihassan) | APPROVED, awaiting merge |
| #61958 | fs.rmSync vs fs/promises.rm discrepancy | #61968 (RajeshKumar11) | Open |
| #61740 | watch: NODE_OPTIONS=--watch infinite loop | #61838, #62143 | Two competing PRs |
| #58231 | test-runner: mocked dual-package gets original | #62943 (maruthang) | Open |
| #59168 | fs.cpSync dereference regression | #62402, #60945 | Two competing PRs |

### Selected issue: #63169 — assert: ERR_INVALID_ARG_TYPE under --enable-source-maps

- **Type:** v26 regression (confirmed-bug equivalent, just unlabeled)
- **Filed by:** twada (power-assert author, respected testing community member)
- **Competing PRs:** None at time of selection
- **Root cause:** `getErrorSourceLocation()` in `lib/internal/errors/error_source.js` returned `undefined` when `--enable-source-maps` was enabled but no source map existed for the file. This propagated through `getErrorSourceExpression()` → `getErrMessage()` → `innerOk()` → `innerFail()`, hitting the `ERR_INVALID_ARG_TYPE` guard.
- **Fix:** Fall back to `{ sourceLine, startColumn }` (generated source line) in all code paths that previously returned bare `undefined`. Added defensive guard for when V8 fails to provide source line at all.
- **Review:** Codex (structural) + Gemini (logic tracing) — both approved. Codex caught the second bare `return;` on line 54. Gemini confirmed zero risk to other callers.
- **Branch:** `kimjune01/node:fix/assert-source-maps-regression`
- **Drip status:** Ready to submit as PR to nodejs/node

### Other notable issues without PRs

| Issue | Title | Notes |
|-------|-------|-------|
| #63186 | vm: SourceTextModule memory leak | Filed by SimenB (Jest maintainer). Requires C++/V8 internals. High impact but out of scope for JS-only fix. |
| #63041 | Intl.DateTimeFormat missing month with iso8601 calendar | ICU upstream regression (ICU 78.1). Needs ICU patch, not Node.js fix. |
| #63067 | V8 fatal CHECK failure with Unicode-escaped eval | V8 upstream bug. |
| #63207 | sqlite: authorizer callback modifies invoking connection | Same author as #63180, likely follow-up. |

## Strategy

1. Submit PR for #63169 (ready now)
2. Monitor #63162 for CI fixes — if it stalls further, it becomes a candidate
3. Re-scan in 1 week for new uncontested issues
4. #63186 (vm memory leak) is high-value if we build C++ familiarity with Node.js internals
