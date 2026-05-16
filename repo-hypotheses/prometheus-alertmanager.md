# Triage Graph: prometheus/alertmanager

## Scan (2026-05-09)

User: kimjune01. 6.7K stars, Go alert routing/grouping.
Status: First contribution. Concurrency bug fix with 5 test cases.

### Triaged issues

| # | Score | Signal | Title | Fix branch | Gate | Status |
|---|-------|--------|-------|------------|------|--------|
| 5103 | 5 | Bug, goroutine leak/panic on client disconnect | /-/reload handler not cancellation-safe | `fix/reload-handler-cancellation-safe` | test: PASS | READY |

### Fix details

**#5103** (2 files, +137 -5)
- File: `httpserver/httpserver.go`
- Three bugs fixed:
  1. Unbuffered error channel: reloader goroutine blocks forever if HTTP client disconnects before reading the result. Fix: `make(chan error, 1)`
  2. `defer close(errc)`: handler is the receiver, not sender; closing from receiver side could panic the sender. Fix: removed
  3. No cancellation awareness: neither the enqueue (send to reloadCh) nor the reply (receive from errc) respected `req.Context().Done()`. Fix: wrap both in `select` with context cancellation
- File: `httpserver/httpserver_test.go`
- 5 test cases: success, error, cancel-during-enqueue, cancel-during-wait, buffered-channel-nonblocking

### Competing PRs

None found for #5103.
