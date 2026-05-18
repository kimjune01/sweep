# prometheus/alertmanager#5234 — `/-/reload` cancellation-safety

PR #5234 (kimjune01, OPEN, BLOCKED merge state). Claims to fix #5103.

## H₀ — The reported bug exists in the real codebase

- **Hypothesis:** `httpserver/httpserver.go`'s `/-/reload` handler has the hang/panic surface described in the issue (unbuffered `errc` + `defer close(errc)` + no ctx-aware send/recv).
- **Perturbation:** Read `httpserver/httpserver.go` at HEAD; compare to issue's claimed pattern.
- **Trajectory:** Divergent — confirmed. Lines 31–38 match exactly: `errc := make(chan error)`, `defer close(errc)`, `reloadCh <- errc`, `<-errc`. No ctx-awareness. Sender (the goroutine that drains `reloadCh`) can panic on `send on closed channel` if the handler returns first; or can block forever on the unbuffered reply if the handler is gone.
- **Mode:** Deduction. Confidence: 98%.
- **Status:** Confirmed.

## H₁ — The issue's file path is wrong; the real file is `httpserver/`

- **Hypothesis:** Issue #5103 names `weboperations/weboperations.go`, which doesn't exist in the repo. The bug actually lives in `httpserver/httpserver.go`.
- **Perturbation:** `ls weboperations/` → no such directory. `ls httpserver/` → `httpserver.go` present with the matching code.
- **Trajectory:** Divergent — confirmed. The bot hallucinated the path; the PR correctly maps the diagnosis to the real file.
- **Provenance:** Issue #5103 was filed by `app/coderabbitai` (bot) on 2026-03-22, citing review comment r2971438549 on PR #5102. r2971438549 was an inline comment whose `path` field is literally `weboperations/weboperations.go`, but PR #5102's actual diff touches `.github/workflows/ci.yml` and UI scaffolding — no Go server code at all. The bot generated a code-review comment against a path that doesn't appear in the diff being reviewed. CodeRabbit hallucination, not a legitimate review finding.
- **Mode:** Induction (file existence) + deduction (PR #5102 diff scope).
- **Status:** Confirmed. Affects framing of the PR: the bug is real; the cited issue's provenance is weak.

## H₂ — The fix matches the canonical Go pattern

- **Hypothesis:** `chan error` size 1 + `select { case reloadCh<-errc: case <-req.Context().Done(): }` + symmetric select on receive is the standard pattern for cancellation-safe ack-channels in Go.
- **Perturbation:** Compare PR diff to standard recipe (Go blog, similar handlers in `prometheus/prometheus`).
- **Trajectory:** Convergent. Matches the bot's suggested diff almost verbatim, minus the bot's bare `return` (PR adds an HTTP 422 + error body, which is a stronger choice — the client may not be gone, it may have a short timeout).
- **Mode:** Deduction. Confidence: 95%.
- **Status:** Confirmed.

## H₃ — CodeRabbit's review of #5234 surfaces a real test antipattern

- **Hypothesis:** Tests call `require.Equal(...)` inside spawned goroutines. `require.*` calls `t.FailNow()`, which is documented as unsafe from non-test goroutines (`testing` package: "FailNow must be called from the goroutine running the test or benchmark function, not from other goroutines created during the test").
- **Perturbation:** Read `httpserver_test.go` from the PR; check each goroutine.
- **Trajectory:** Divergent — confirmed. All four new tests (`TestReloadSuccess`, `TestReloadError`, `TestReloadClientDisconnectBeforeEnqueue`, `TestReloadClientDisconnectDuringReload`) call `require.Equal` inside `go func() { ... }()`. On failure, behavior is undefined (FailNow only marks the calling goroutine; the test may hang or finish "passing" depending on scheduling).
- **Kill condition:** None — the issue is genuine.
- **Edge:** Refactor — capture `w.Code` / `w.Body` into local vars inside the goroutine, signal completion via the existing `done` channel, then assert in the main test goroutine. Or swap `require` → `assert` (logs failure, doesn't FailNow) inside the goroutine, but the channel-capture form is cleaner.
- **Mode:** Deduction (Go stdlib docs). Confidence: 98%.
- **Status:** Confirmed. Actionable.

## H₄ — Merge is BLOCKED for a reason other than tests

- **Hypothesis:** `mergeStateStatus: BLOCKED` despite `mergeable: MERGEABLE`, DCO passing, no human review yet. Likely cause: branch protection requires approving review.
- **Perturbation:** Check `reviewDecision: ""` (no decision) + only review is CodeRabbit "COMMENTED" — no APPROVE from a maintainer.
- **Trajectory:** Convergent. The block is policy (needs maintainer approval), not a test/CI failure.
- **Mode:** Induction. Confidence: 85%.
- **Status:** Confirmed.

## Graph state

| Node | Status | Mode | Confidence |
|------|--------|------|------------|
| H₀ bug-is-real | confirmed | deduction | 98% |
| H₁ wrong-path-in-issue | confirmed | induction+deduction | 95% |
| H₂ fix-is-canonical | confirmed | deduction | 95% |
| H₃ test-antipattern | confirmed | deduction | 98% |
| H₄ merge-blocked-on-approval | confirmed | induction | 85% |

## Frontier

- None. All edges close.

## Diagnosis

The fix is correct. The test file has a real Go testing antipattern (require in goroutine) that CodeRabbit flagged and should be addressed before pushing for human review. The "Fixes #5103" link is to a bot-hallucinated issue, but the bug being fixed is genuine.

## Recommended action

1. Refactor the four new tests to assert in the main test goroutine (channel-capture pattern), then force-push.
2. Optionally trim the PR description's reliance on "Fixes #5103" — the issue is hallucinated provenance; the bug-and-fix stand on their own. Phrasing like "Addresses the unbuffered-reply hang flagged by review on #5102" is more honest.
3. Wait for maintainer review (the BLOCKED merge state is just missing approval).
