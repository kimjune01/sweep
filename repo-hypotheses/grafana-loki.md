# grafana/loki Triage Graph

Repo: grafana/loki (28K stars, Go, log aggregation)
Warm lead: grafana org, pyroscope PR already open
Blocked: org-level push block on grafana repos (pyroscope PR occupies the slot)

## Issue Scan Summary

Scanned: good-first-issue (8), type/bug (29 recent), help-wanted labels
Date: 2026-05-09

## Selected: #21669 (canary -labels/-query-append ignored)

- **Type:** bug fix
- **Component:** loki-canary (pkg/canary/reader)
- **Filed:** 2026-04-22 by marek-obuchowicz
- **Comments:** 0 (no maintainer interaction yet)
- **Competing PRs:** 0
- **Labels:** component/loki-canary, type/bug

### Root cause

The `-labels` and `-query-append` CLI flags were only wired into `Query()` (spot checks). Two other query paths -- `QueryCountOverTime()` (metric queries) and `closeAndReconnect()` (websocket tail) -- hardcoded the old `{sName="sValue",lName="lVal"}` selector and omitted `queryAppend` entirely.

### Fix

- Extracted `buildLabelsQuery()` helper, used by all three query sites
- Used `strings.Cut` for label parsing (handles `=` in values)
- Added whitespace trimming and empty key/value validation
- Early validation in `NewReader()` to fail fast on config errors
- Added 8 unit tests for `buildLabelsQuery()`
- Changed `%v` to `%s` for queryAppend formatting

### Review trail

- codex (GPT-5.5): approved core approach, flagged strings.Cut, whitespace trimming, early validation (all addressed)
- gemini (3.1 pro preview): confirmed LogQL placement is correct, flagged infinite loop risk in closeAndReconnect (mitigated by 10s backoff + early validation)

### Branch

`fix/canary-labels-query-append` on kimjune01/loki

## Rejected Issues

### #18788 (nginx.conf typo) -- good-first-issue
- **Reason:** 3 competing PRs already open (#21714, #21652, #18870)
- Dead on arrival

### #20673 (replace uber atomic with sync/atomic) -- good-first-issue
- **Reason:** Massive scope (entire codebase refactor), contributor warned Prometheus PR was rejected
- High risk of rejection, not a bug fix

### #20288 (lint/check naming inversion) -- good-first-issue
- **Reason:** Maintainer (chaudum) already opened PR #21671 to fix it
- Solved by maintainer

### #7450 (ruler endsAt time) -- good-first-issue
- **Reason:** 4+ years old, assigned contributor stalled, requires upstream Prometheus changes
- Blocked by external dependency

### #21596 (Azure SAS token bug) -- type/bug
- **Reason:** Storage-layer bug requiring Azure test environment
- Cannot verify without Azure credentials

### #21669 alternatives considered
- #21232 (canary duplicate logs) -- 4 comments, more complex, requires websocket state machine understanding
- #20326 (shard_aggregations parsing error) -- LogQL parser internals, higher risk

## Pipeline Status

- **Org block:** grafana org push blocked (pyroscope PR open)
- **Action:** PR ready locally. Push when org block clears or pyroscope PR merges/closes.
- **Next:** Monitor pyroscope PR status. When unblocked, push branch and open PR via `gh pr create`.
