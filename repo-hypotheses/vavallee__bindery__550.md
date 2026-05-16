# vavallee/bindery#550 — fire-and-forget goroutine context audit

**Issue:** `internal/api/recommendations.go:167` (and #176) spawn goroutines with `context.Background()` instead of an app-rooted context. Goroutine can outlive graceful shutdown, holding DB conns and upstream sockets.

**Maintainer note (issue body):** "Needs an audit of every 'fire and forget' goroutine in the codebase to apply consistently, not a single-file patch." Prior triage denylisted #550 for this reason. The audit *is* the deliverable; this document is it.

**Investigation date:** 2026-05-16
**Source tree:** `/tmp/bindery` (vavallee/bindery, main as of 2026-05-11 triage)

---

## H₀ — observation (deduction, 99%)

`cmd/bindery/main.go:908` does create a `signal.NotifyContext` (`sigCtx`), but it is used **only** for `srv.Shutdown` at line 942. It is never passed to:
- the scheduler (`sched.Start()` has no ctx param — scheduler.go:192),
- the two startup goroutines (calibre import line 324, prowlarr sync line 344),
- any handler constructor.

There is no app-root cancellable context plumbed into the rest of the system. Every long-running goroutine that wants to outlive a request currently picks one of three patterns, inconsistently.

### Three patterns in use today

| Pattern | Call sites | Behavior on shutdown |
|---|---|---|
| Raw `context.Background()` | rec, scheduler jobs, startup syncs, cache loops | Survives forever; holds DB/HTTP resources |
| `context.WithoutCancel(r.Context())` | library.go:38, series.go:415, books.go:298 | Survives request, but **also** survives shutdown |
| `contextBackground()` helper (api/helpers.go:36) | authors.go, bulk.go | Wraps `context.Background()` — same as pattern 1 |

The `contextBackground()` helper is the seam — it already exists as a single chokepoint. If it returned `appCtx`, three of the worst offenders (`authors.go`, `bulk.go`) flip in one edit.

---

## Inventory — every fire-and-forget goroutine

Grepped `^\s*go ` across non-test `.go` files and classified by lifecycle.

### A. Request-triggered, must survive HTTP response (correct today)

| Site | Pattern | Status |
|---|---|---|
| `internal/api/library.go:38` | `WithoutCancel(r.Context())` | ✓ outlives request, inherits request values |
| `internal/api/series.go:415` | `WithoutCancel(ctx)` | ✓ |
| `internal/api/books.go:298` | `WithoutCancel(r.Context())` | ✓ |

Gap: these *also* survive app shutdown indefinitely. To honor #550's spirit they should derive from an app-rooted cancellable context too — but they're not the obvious bug, so deferring this tier is reasonable.

### B. Request-triggered, currently using `context.Background()` (the #550 cases)

| Site | What it spawns |
|---|---|
| `internal/api/recommendations.go:167` | `searcher.SearchAndGrabBook` after adding book from recommendation |
| `internal/api/recommendations.go:176` | `engine.Run` for manual refresh |
| `internal/api/authors.go:756, 1294` | author-book fetch + optional search (via `contextBackground()`) |
| `internal/api/bulk.go:110, 180, 235` | bulk search (via `contextBackground()`) |
| `internal/api/auth_oidc.go:405` | OIDC provider Reload (uses `r.Context()` — cancels on response, opposite bug) |

These should all use a context that (a) survives the request, (b) cancels on app shutdown. Either `appCtx` directly, or `context.WithoutCancel(r.Context())` *if* `r.Context()` is itself derived from `appCtx` via the chi server (it isn't today — `http.Server` uses `context.Background()` by default unless `BaseContext` is set).

### C. App-scoped long-running (no shutdown signal at all)

| Site | What it spawns |
|---|---|
| `internal/metadata/ttl_cache.go:25` | 1h ticker, runs forever |
| `internal/api/imageproxy.go:61` | one-shot `migrateFlatCache` |
| `internal/api/imageproxy.go:214` | eviction ticker, runs forever |
| `internal/db/log_handler.go:43` | log drainer (has explicit Stop, used by main's defer at 129) ✓ |

The two ticker loops never stop. The log handler already does the right thing.

### D. Startup-only, raw `context.Background()`

| Site | What it spawns |
|---|---|
| `cmd/bindery/main.go:324` | calibre startup import |
| `cmd/bindery/main.go:344` | prowlarr per-instance startup sync |

### E. Cron-driven jobs (scheduler.go), raw `context.Background()`

| Line | Job |
|---|---|
| 199 | check-downloads (15s) |
| 207 | check-stalled (5m) |
| 225 | scan-library (6h) |
| 232 | calibre-sync (24h) |
| 241, 245 | recommendations (24h, settings read + run) |
| 255 | hardcover-sync (24h) |
| 264, 267 | telemetry-ping (24h + startup) |
| 281, 288 | log-trim (24h) |

`Scheduler.Stop()` cancels the cron scheduler itself (`s.cron.Stop()` returns a ctx that signals when all running jobs finish), but each job's *inner* context is `context.Background()` — so a job in flight at shutdown gets no cancellation signal even though `Stop()` waits for it. Inverts the relationship: scheduler waits forever for jobs that never know to stop.

### F. Bounded-fan-out worker pools (correct, sync on caller's ctx)

`indexer/searcher.go`, `indexer/debug.go`, `metadata/openlibrary/client.go`, `scheduler.go:599`, `authors.go:1000` — all use `wg.Wait()` and inherit the caller's context. Not in scope.

### G. CLI/test goroutines

`migrate/csv.go:113`, `migrate/readarr.go:135`, `migrate/readarr_importer.go:103`, `calibre/importer.go:136`, `calibre/syncer.go:134`, `abs/importer.go:237`, `importer/renamer.go:378,449,461`. These take a `ctx` parameter and pass it through — the bug lives at the call site, not here.

---

## H₁ — proposed fix shape (abduction, 75%)

Introduce `appCtx` in `main.go` and plumb it as a constructor argument to the components that own background lifecycles. Three layers:

1. **Lift the existing `sigCtx`** from main.go:908 up to right after `bootstrapAuth` (around line 170). Rename `appCtx, stopApp`. The HTTP server's `BaseContext` can use it too, which makes `r.Context()` a child of `appCtx` for free — meaning today's `context.WithoutCancel(r.Context())` calls flip from "survives shutdown forever" to "survives the request, cancels on shutdown" without any code change at the call site.

   ```go
   srv := &http.Server{
       BaseContext: func(net.Listener) context.Context { return appCtx },
       // ...
   }
   ```

2. **Pass `appCtx` to `Scheduler.Start`**. Each job's inner `context.Background()` becomes `appCtx`. `Stop()` now actually cancels in-flight jobs (the cron stop and the ctx cancel are paired). Startup goroutines in main (calibre, prowlarr) take `appCtx` directly.

3. **Replace `contextBackground()`** with a method on a `Backgrounder` interface stored on handlers, returning `appCtx`. Constructors gain an `appCtx context.Context` arg. Tests pass `context.Background()` explicitly. This catches authors.go, bulk.go, recommendations.go in one mechanical pass.

4. **Cache loops** (`ttl_cache.go`, `imageproxy.go` eviction): constructor takes ctx, ticker loop selects on `<-ctx.Done()`. One-shot `migrateFlatCache` takes ctx as arg.

5. **OIDC Reload** (auth_oidc.go:405): switch from `r.Context()` to `context.WithoutCancel(r.Context())` — opposite-direction fix from the rest, same family of bug.

**Estimated diff:** ~300 LOC, ~15 files. Almost entirely mechanical once the seam is added.

---

## H₂ — risks (abduction → for testing, 60%)

What can go wrong with this plumbing:

- **R1: In-flight searches cancelled mid-grab.** A `SearchAndGrabBook` that's downloading a torrent metadata file when SIGTERM arrives now bails. Today it completes (and holds the socket). The maintainer's deferral note flags this exactly: "a wrong cancellation point can break in-flight searches." Mitigation: use the existing 30s `BINDERY_SHUTDOWN_GRACE` window — `appCtx` cancel happens, but Shutdown waits up to `gracePeriod` for the jobs to drain.
- **R2: Goroutine leaks if a constructor takes ctx but never wires it through.** Caught by `go vet` and review, not silent.
- **R3: Cron `Stop()` semantics now double-up with appCtx cancel.** Need to confirm robfig/cron's Stop returns when in-flight `Run` invocations complete or when the ctx is cancelled — read the lib before relying on it.
- **R4: Tests that construct handlers without an appCtx break.** Mechanical: tests pass `t.Context()` (Go 1.24+) or `context.Background()`.
- **R5: The `recommendations.go:167` `#nosec G118` annotation** flags this as intentional ("search must outlive the request"). The fix preserves that — appCtx outlives the request — but the comment needs updating.

Each risk gets a test before shipping; this is what makes #550 "an audit" rather than "a single-file patch."

---

## Frontier — what stays open

1. **Tier A** (`WithoutCancel(r.Context())` sites): does step 1 (BaseContext) actually make them shutdown-bound? Needs a smoke test — start server, fire a /library/scan, send SIGTERM, observe the scan context cancels. Predicted: convergent confirm.
2. **robfig/cron Stop semantics** under appCtx cancel: predicted convergent. Read the lib.
3. **Whether to fold tier A into this PR** or ship in two PRs: judgment call. The "audit" framing argues for one PR; the "narrow diff" CONTRIBUTING preference argues for splitting. Probably split: PR1 = appCtx + scheduler + startup + cache loops + recommendations (the #550 cases). PR2 = `contextBackground()` deprecation across authors/bulk. PR3 = tier A re-derivation through BaseContext, if needed.

---

## Provenance check

- `recommendations.go:167` — the `#nosec G118` comment is deliberate, not an oversight. Maintainer chose `context.Background()` knowing the linter would complain. The fix needs to preserve "outlives the request" while adding "but not forever."
- `internal/api/library.go:38` comment ("`context.WithoutCancel` so the goroutine isn't killed when the HTTP response is sent and the request context is cancelled") shows the maintainer already understands the pattern. The asymmetry across the codebase is drift, not principle.
- No existing PR addresses #550 (`gh pr list --repo vavallee/bindery --search "context.Background goroutine"` empty as of triage 2026-05-11). Sister issues #548, #549, #547 in same denylist cluster — all maintainer-deferred audits.

---

## Reasoning mode table

| Claim | Mode | Confidence |
|---|---|---|
| No app-root context is plumbed | Deduction (read main.go) | 99% |
| Inventory of fire-and-forget sites is complete | Induction (grepped `^\s*go ` in non-test files, classified each) | 92% — small chance of `defer go func()` or factory-spawned goroutines missed |
| `contextBackground()` is the seam | Deduction | 95% |
| `BaseContext` makes `r.Context()` shutdown-bound | Deduction (net/http docs) | 95% |
| Fix shape is ~300 LOC | Abduction | 60% |
| Risk R1 (in-flight cancel) is real and mitigated by shutdown grace | Abduction | 70% — needs a test |

---

## Decision point (human gate before prework)

The investigation produces the audit the maintainer asked for. Three forward paths:

1. **Stop here** — paste this audit as a comment on #550, let the maintainer decide scope. Low risk, no PR, respects the explicit deferral.
2. **Ship the narrow PR** (scheduler + startup + cache loops + recommendations only, ~150 LOC) and link this audit as the rationale for the broader follow-ups.
3. **Ship the full audit PR** (~300 LOC, ~15 files) — closer to what the issue asks for, but exactly what the maintainer flagged as risky.

Recommend path 1 or 2. Path 3 is what the issue says, but the issue is on the denylist for a reason.

**Frontier-closed?** No — the graph names the next experiments (BaseContext smoke test, robfig/cron Stop semantics) but they're cheap deductions, not blocking. The human gate on path choice is the real next step.
