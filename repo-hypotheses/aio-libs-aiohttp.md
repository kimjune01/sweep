# TRIAGE GRAPH — aio-libs/aiohttp

## REPO CONTEXT
- Default branch: master
- Target branch for PRs: master
- CONTRIBUTING: CONTRIBUTING.rst — fork, change, test, add CHANGES/ file, PR against master
- PR template: requires "What do these changes do?", "Are there changes in behavior?", related issue, checklist
- CHANGES file: `CHANGES/<issue_or_pr_num>.bugfix.rst` with past-tense sentence and `:user:` credit
- CONTRIBUTORS.txt: add self in alphabetical order
- No anti-AI policy found
- No AGENTS.md

## MAINTAINER PREFERENCES
- Dreamsorcerer (MEMBER): active reviewer, opened test-only PR #10587 for issue #10322
- bdraco (MEMBER): active contributor, diagnosed #10322
- webknjaz (MEMBER): active reviewer

## ISSUE RANKINGS (top 5)

### 1. #10322 — HEAD response body crashes C parser [WORKED — qa_ready]
- **Score**: 9/10 — confirmed bug, maintainer-diagnosed, no competing PRs, C parser specific
- **Branch**: fix/head-response-body-cparser
- **Status**: test + fix committed, pushed to fork
- **Competing PRs**: none (PR #10587 is test-only, never landed)

### 2. #9308 — BaseRequest.host can do blocking I/O
- **Score**: 6/10 — confirmed by bdraco, but "no solution without breaking change"
- **Competing PRs**: none
- **Risk**: breaking change, bdraco couldn't find a non-breaking fix
- **Status**: SKIPPED — too risky for first contribution

### 3. #10355 — Missing CRLF at end of chunk in malformed chunked encoding
- **Score**: 5/10 — has open competing PR #10359 (xdegaye)
- **Status**: SKIPPED — competing PR exists

### 4. #10047 — Redirects with ø char parsed wrongly
- **Score**: 5/10 — has competing PR #12325 (MAXDVVV)
- **Status**: SKIPPED — competing PR exists

### 5. #10142 — Invalid error message for HTTPS on HTTP port
- **Score**: 4/10 — competing PR #12447 was closed, could retry
- **Risk**: closed PR suggests maintainer may not want change
- **Status**: DEFERRED

### DEFERRED
- #9308 — BaseRequest.host blocking I/O — no non-breaking fix available
- #10142 — HTTPS on HTTP port error message — nightcityblade claimed it
- #10096 — sendfile fallback removal — cleanup, not a bug fix
- #9891 — IPv6 disabled test failures — can't verify locally
- #2928 — Response.text AttributeError — 2 competing PRs (#12239, #12138)
- #5324 — on_response_chunk_received tracing — competing PR #7455

### SKIPPED (competing PRs)
- #10355 — chunked CRLF — open PR #10359
- #10047 — redirect ø char — open PR #12325
- #10860 — hash dirs in wheels — open PR #12500
- #12497 — TCPConnector.close() race — open PR #12498
- #12404 — BodyPartReader bytearray — flooded with AI PRs, maintainer displeased

## KILLED / DENIED
(none yet)

## EVIDENCE LOG
- 2026-05-12: #10322 test fails on c-parser with "Invalid character in chunk size: b'\x1f\x8b\x08'" — confirmed bug
- 2026-05-12: Fix: return 1 from cb_on_headers_complete when response_with_body=False + suppress parse error for leftover body bytes
- 2026-05-12: 726/726 parser tests pass with fix
