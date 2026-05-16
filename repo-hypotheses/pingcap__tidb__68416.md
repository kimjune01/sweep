# pingcap/tidb#68416 — `make bench-daily` hangs on `analyze table t`

**Status:** Halted at idempotency guard. Maintainer (issue author 0xPoe) already opened WIP PR #68417 one minute after filing the issue. No PR from us.
**Started:** 2026-05-16

## H₀ — Observation

`make bench-daily` → `BenchmarkNonPartitionPointGetPlanCacheOn` fails with:

```
[FATAL] mustExecute error  sql="analyze table t"  error="context deadline exceeded"
  pkg/store/copr.(*copIterator).Next
  pkg/executor.broadcast (simple.go:3034)
  pkg/executor.flushStatsDeltaForAnalyze (analyze.go:128)
```

10s deadline. Failure log: `tiprow.hawkingrei.com/.../gobench4/2054509118642720768`.

**Trajectory:** Divergent. Reporter (0xPoe) has already traced the cause in the issue body.

## H₁ — `intest.InTest` gate misses the bench path

**Hypothesis:** `flushStatsDeltaForAnalyze` (added in #67939, merged 2026-04-29) broadcasts `FLUSH STATS_DELTA CLUSTER` via a TiDB-type cop request unless `intest.InTest` is true. `intest.InTest` is gated on the `intest` build tag. `make bench-daily` runs `go test` without `-tags=intest`, so the broadcast path executes against the mockstore-backed in-process domain. In-process domains register server info with empty `AdvertiseAddress`, so the broadcast targets `:10080` and burns RPC backoff until the bench's 10s deadline trips.

**Perturbation:** Read the code path.

**Evidence (deduction, ~98%):**

- `pkg/executor/analyze.go:91-122` — `flushStatsDeltaForAnalyze` gates the local-dump fallback on `if intest.InTest { ... }`. Outside that branch it falls through to `broadcast(ctx, sctx, sql)`.
- `pkg/util/intest/in_unittest.go` — `var InTest = true` under `//go:build intest`.
- `pkg/util/intest/not_in_unittest.go` — `var InTest = false` under `//go:build !intest`.
- `Makefile` `bench-daily` target — four `go test ... -run TestBenchDaily -bench Ignore` lines, none with `-tags=intest`.
- The existing `canBroadcastAnalyzeStatsDeltaForTest` already handles the in-process case: `if server.IP == ""` it skips the dial and treats the server as unreachable → falls back to local dump. The mechanism is correct; only the gate is wrong.

**Trajectory:** Divergent confirm. Single root cause, exact mechanism match.

**Mode:** Deduction (read the code, traced the units and build tags). Reporter and PR author #67939 is the same person, so this is essentially a self-diagnosed bug.

## H₁.provenance

- Bug introduced by PR #67939 (merged 2026-04-29, author 0xPoe).
- Issue #68416 filed 2026-05-15 by the same author after the bench-daily CI job (`gobench4`) failed.
- WIP PR #68417 (`executor: skip analyze flush broadcast when AdvertiseAddress is empty`) opened by 0xPoe at 2026-05-15T16:52:51Z — **one minute after** the issue was filed.
  - Diff: `pkg/executor/analyze.go` +9/-6 only.
  - Approach: broaden the gate to also fire when `config.GetGlobalConfig().AdvertiseAddress == ""`. No-op in production (real `tidb-server` always populates it), catches in-process bench/test topologies reliably.
- Adjacent context: PR #68146 (`executor: use statement context for pre-analyze stats flush`, merged 2026-04-30) — same author tightening the same code path. They are actively iterating on this function.

## Halt — Idempotency guard

Per `/investigate` rules:

> If someone else's PR addresses the same issue: link to it in the graph document and stop. The investigation becomes evidence for their PR, not a competing one.

The maintainer has it, the diagnosis matches, the fix is minimal (+9/-6 in one file), and #68417 was opened within 60s of the issue. There is no opening for an outside contributor here.

**Decision:** Do not draft a PR. Do not post a "looking at this" claim — the author of the bug is fixing their own bug, and any external claim would be noise.

## Graph state

| Node | Status | Trajectory | Mode |
|------|--------|------------|------|
| H₀ bench hangs on `analyze table t` | observed | divergent | induction (CI log) |
| H₁ intest.InTest gate misses bench (no -tags=intest) | confirmed | divergent | deduction |
| Fix shape (broaden gate with AdvertiseAddress empty check) | already in PR #68417 (WIP, 9/-6) | — | — |

## Reframe

The investigation didn't generate new information — the issue body was already a complete root-cause analysis by the reporter. The reframe is meta: **issues where the reporter is also the PR author and they file the issue + open the WIP PR within the same minute are not contribution opportunities.** They are public worklog entries. The triage filter should drop these earlier.

Save as feedback for prospect/triage: when issue body reads like a maintainer's own post-mortem (cites internal CI job name, names the specific PR that introduced the bug, identifies the exact gate that's wrong, and the reporter has commit access), check for an author-self-PR before investigating.

## Frontier

Closed. No open edges. Halt at depth 1.
