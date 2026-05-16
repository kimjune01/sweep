# hyperium/hyper#4049 — H2 CONNECT UpgradedSendStreamTask bypasses h2 flow control

**Status:** HALT — author's PR #4050 already open, CI green, awaiting review.

## Halt rationale

The issue reporter (`abbshr`) filed a fully-diagnosed bug report and opened the
fix as PR #4050 on the same date. Per `/investigate` idempotency guard:

> If someone else's PR addresses the same issue: link to it in the graph
> document and stop. The investigation becomes evidence for their PR, not a
> competing one.

A duplicate PR from us would burn maintainer attention with no marginal value.
The author has direct standing — they observed the production OOM, traced the
backpressure chain, and supplied the one-line fix that already has all CI
green on stable/beta/nightly across linux/mac/windows + Miri + MSRV + FFI.

## H₀ — the report itself is the diagnosis

**Hypothesis:** `UpgradedSendStreamTask::tick()` in `src/proto/h2/upgrade.rs:98`
uses `break 'capacity` where it should use `return Poll::Pending`, so when h2
flow control returns no capacity, the outer `loop { }` proceeds to drain the
mpsc channel and call `send_data()` anyway. `h2::SendStream::send_data()` does
not enforce flow control — it buffers indefinitely into `pending_send`. The
mpsc(1) channel is therefore always empty, `H2Upgraded::poll_write` is never
`Pending`, the bidi copy loop reads from upstream at line rate, all delta
accumulates in the per-stream send buffer.

**Reasoning mode:** deduction (read the code, traced consequences across hyper
+ h2). Confidence: 95%+ — the call graph is mechanical, the bug is local, and
the production timeline (165MB → 8GB in 39s, inbound 1.55 Gbps vs outbound 89
Mbps) matches the predicted dynamics quantitatively.

**Null:** `break 'capacity` is intentional because some other mechanism
re-suspends the task before `send_data` is called.

**Perturbation (already run by reporter):** production traffic with fast
upstream + slow downstream; observed unbounded RSS growth, two pod OOMs.
Author also compared against pre-#3967 implementation which used `ready!()` on
`poll_capacity` directly — that path had correct backpressure.

**Trajectory:** divergent against the null. The bug is real, the fix is
one line.

## Provenance check

- **Origin:** PR #3967 (refactor to remove `unsafe` transmute via `Neutered<B>`).
  Introduced the two-task + `mpsc::channel(1)` architecture. The intent —
  channel-as-backpressure — is sound; the implementation broke the chain at
  one branch.
- **Upstream issues:** the reporter cites
  [rust-lang/rust#147588](https://github.com/rust-lang/rust/issues/147588) as
  motivation for #3967 (the old `Neutered` transmute may break on future
  rustc). So reverting is not an option; fixing #3967's bug is.
- **Existing PR:** #4050 by `abbshr`, opened 2026-04-09, CI fully green
  (stable/beta/nightly × ubuntu/macOS/windows, Miri, MSRV, FFI, semver, docs).
  Status: `REVIEW_REQUIRED`, mergeable. Diff +288/-5 — fix is one line, rest
  is presumably a regression test.

## Frontier edges (left open for the maintainer / PR reviewer)

These are concerns worth raising in the PR review, not new investigations
worth shipping as separate PRs:

1. **Wakeup correctness.** When `poll_capacity` returns `Pending`, h2 has
   registered the current task's waker. Returning `Poll::Pending` from `tick`
   means the task will be re-polled when capacity arrives — verify the waker
   really is the `tick` task's waker and not some inner h2-internal one that
   gets dropped.
2. **Test attestation: fail-on-master, pass-with-fix.** The +288 lines
   probably include a regression test; reviewer should verify the test fails
   without the one-line change. (Skill rule: a test that passes on master
   proves nothing.)
3. **Other `break 'capacity`-shaped escapes** elsewhere in the file — sibling
   patterns may share the bug.

## Halt and link

- Issue: hyperium/hyper#4049
- Author PR: hyperium/hyper#4050 (open, CI green)
- Action: none from us. Do not open a competing PR. If maintainer wants
  independent confirmation, the analysis above is the artifact.
