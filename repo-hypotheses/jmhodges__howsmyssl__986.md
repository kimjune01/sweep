# jmhodges/howsmyssl#986 — enable HTTP/2

**Status:** Already shipped. No PR to open.

## H₀ — The issue describes work-to-do

**Hypothesis:** Issue #986 (filed 2026-04-26 by maintainer jmhodges) describes outstanding work to enable HTTP/2: NextProtos additions plus `Connection: close` on all responses (which the Go http2 stack converts to a GOAWAY frame). Connection closing is required to prevent memory build-up from retained `clientHelloMsg` data per request.

**Perturbation:** `git log --oneline` on the default branch + `gh pr view` on PRs around the issue date.

**Result:**
- Commit `f64f859f` ("enable HTTP/2 via new howhttp package") landed via PR #1013, merged 2026-05-14T19:42:18Z (2 days ago).
- The PR adds a `howhttp` package that serves HTTP/1.1 and HTTP/2 on the same `tls1262` listener by ALPN-dispatching to `http2.Server.ServeConn` for `h2` and to the wrapped `*http.Server` otherwise.
- `howsmyssl.go:316` still sets `w.Header().Set("Connection", "close")` with a comment explicitly citing the GOAWAY behavior on HTTP/2 — the exact mechanism the issue calls for.
- `howhttp/concurrent_test.go` exercises both HTTP/1.1 and multiplexed HTTP/2 paths; `howhttp/smoke_test.go` checks `Connection: close` semantics.

**Trajectory:** Divergent — the work described in the issue exists, has tests, and was merged by the same author who filed the issue. Hypothesis killed in the sense that there is no remaining work-to-do.

**Reasoning mode:** Induction (read shipped code + merged PR). Confidence: 95%.

## Provenance

- Origin of fix: PR #1013 by jmhodges, merged 2026-05-14.
- The PR body does **not** include `Closes #986`, which is why the issue remains in OPEN state despite the work shipping. `closingIssuesReferences` is empty.
- The CPU-vs-memory tradeoff musing at the end of the issue (IdleTimeouts vs `Connection: close`) was resolved in favor of keeping `Connection: close` — the comment at `howsmyssl.go:310-315` explains the choice (avoid races, prevent TLS resumption breaking vuln detection).

## Decision

**Do not open a PR.** Three reasons:
1. The work is shipped. A duplicate PR would be noise.
2. The issue author is the implementer; they know it's done. They likely just didn't link the issue in the PR body.
3. The most useful possible PR — closing the issue — is not appropriate for an outside contributor on a single-maintainer repo. The maintainer can close it in one click.

Per the skill's idempotency guard: *"If someone else's PR addresses the same issue: link to it in the graph document and stop."* Here, the maintainer's own PR addresses it. Same rule applies.

## Frontier

Closed. No open edges. The investigation halts.
