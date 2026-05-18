# opensquilla/opensquilla#21 — Fix RuntimeError: aclose() race

**Subject.** PR #21 by `kimjune01` (the operator) fixing issue #14 (reporter: `ab2ence`). Single targeted edit in `src/opensquilla/engine/agent.py::_stream_provider_events_with_deadline`: removes one `await self._close_provider_stream(stream_iter)` call after a cancelled `await next_event` under the iteration-timeout branch.

**Context flags.**
- PR author is the operator. Not an upstream-investigation; this is a self-PR review.
- PR is `mergeable: CONFLICTING`. Diff is **16,734 additions / 1,706 deletions across ~100 files** for what is functionally a one-line fix. The branch is badly out of sync with main and is carrying massive unrelated drift (channels, gateway, CSS, onboarding, README, etc.). CI is green on the head, but the PR will be unreviewable in this shape.
- Issue #14 reporter is on Windows 10; reproduces during multi-agent autostop. Bug surfaces as an asyncio "Task exception was never retrieved" warning, not a raised exception.

---

## H₀ — Baseline claim

> Removing the `_close_provider_stream(stream_iter)` call after `await next_event` (under `contextlib.suppress(CancelledError, StopAsyncIteration)`) prevents `RuntimeError: aclose(): asynchronous generator is already running`.

**Trajectory shape (so far): partial / oscillatory.** The diagnosis is structurally plausible — cancelling the `__anext__` task throws `CancelledError` into the generator, which starts its `finally` block; calling `aclose()` while the generator is mid-cleanup raises the RuntimeError. But two load-bearing pieces fail provenance check.

---

## H₁ — The test does not fail on master (kill: divergent against)

**Hypothesis.** `tests/test_engine/test_aclose_race.py::test_timeout_does_not_double_close_generator` will fail on master and pass with the fix.

**Perturbation.** Read the test:

```python
with pytest.raises(_IterationStreamTimeoutError):
    async for _ in agent._stream_provider_events_with_deadline(...):
        pass
```

It asserts only that `_IterationStreamTimeoutError` is raised. That exception is raised on **both** the buggy and the fixed code path (line 1944 / 1965). Nothing in the test captures the RuntimeError, the asyncio "Task exception was never retrieved" warning, or any logger output.

The test's own docstring concedes this:

> "The current buggy code suppresses the RuntimeError in `_close_provider_stream`, but we can verify the bug by checking that no RuntimeError would occur in the log. For this test, we just verify it doesn't raise."

But the test never inspects the log either. It is a "passes on master, passes with fix" test — a no-op gate.

**Classification: divergent against.** This violates the substrate's hard rule (`feedback_test_must_fail_on_master` lineage in CLAUDE.md investigate skill): *"A test that passes on master proves nothing — we learned this by shipping one and getting called out by a reviewer."*

**Edge.** The test needs one of:
- `pytest.warns(...)` or `caplog` assertion that no `RuntimeError` is emitted to the `opensquilla.engine.agent` logger at DEBUG.
- Custom `loop.set_exception_handler` that records orphan-task exceptions; assert the recorder is empty.
- Direct white-box: build a generator whose `finally` records whether `aclose()` was called from inside its own running cleanup.

Without this, the regression test does not regress.

---

## H₂ — The diagnosis matches the user's reported symptom only partially (kill: provenance gap)

**Hypothesis.** The path being patched is the path that produced the user's traceback.

**Perturbation.** The user's traceback:

```
Task exception was never retrieved
future: <Task finished name='Task-24440'
  coro=<<async_generator_athrow without __name__>()>
  exception=RuntimeError('aclose(): asynchronous generator is already running')>
```

The orphan task's coro is `async_generator_athrow` — the awaitable returned by `gen.athrow()` (which `aclose()` uses internally). For this to surface as "Task exception was never retrieved," the `aclose()` awaitable must have been scheduled **as a Task** and then never awaited.

But `_close_provider_stream` awaits `aclose()` directly:
```python
await aclose()
```
and its outer caller does `await self._close_provider_stream(stream_iter)`. Nowhere in the patched path is `aclose` wrapped in `ensure_future` / `create_task`.

So either:
1. Some other code path (callback, garbage-collected generator, `__del__`-triggered cleanup, or a different cancellation site) is producing the orphan athrow task that ab2ence is seeing, and the patched site is a different defect that the operator inferred from reading the code; **or**
2. There's a subtle asyncio behavior where awaiting a cancelled `__anext__` task returns *before* the inner generator's `finally` fully completes (e.g., if the finally has its own `await` that suspends), leaving the generator in "running" state while `_close_provider_stream` then calls `aclose()`. This would explain the error message but the orphan-task framing in the traceback still doesn't fit cleanly.

**Classification: convergent partial.** The diagnosis explains *a* RuntimeError that matches the message, but the orphan-task framing in ab2ence's traceback is unexplained. The fix may improve the situation; whether it eliminates ab2ence's specific symptom is unverified.

**Edge.** Before claiming "fixes #14," need:
- A reproducer that emits the exact `Task exception was never retrieved` warning on master.
- Either grep for other `aclose` / `athrow` / `ensure_future(...athrow...)` sites in the engine that could orphan a task, **or** prove that `await task` of a cancelled `__anext__` can return before the generator's finally completes.
- A version of the test that asserts the orphan-task warning is absent under the fix.

---

## H₃ — Other `_close_provider_stream` callsites on the same function are still reachable (open)

**Hypothesis.** The two surviving calls at the top of the `while True` loop (lines 1943 and 1950) cannot hit the same race.

**Perturbation.** Read paths:
- Line 1943 / 1950 run *before* `next_event` is created in the current iteration. They fire when `remaining_iter <= 0` / `remaining_total <= 0` at loop entry. The generator at that point is not currently mid-`__anext__` (the previous iteration completed normally via `yield next_event.result()`). So `aclose()` here closes an idle generator → safe.

**Classification: convergent for.** These paths are fine. No fix needed.

---

## H₄ — The PR shape will be rejected before the fix is reviewed (open, high confidence)

**Hypothesis.** 16k+ additions across 100+ unrelated files on a one-line targeted fix will be closed-without-review.

**Perturbation.** Sample the file list: `README.md +408 -58`, `install.ps1 +156 -12`, `gateway/static/css/views/setup.css +645 -247`, `channels/feishu.py +268 -34`, `onboarding/flow.py +777 -100`. None of these are part of the diagnosed bug. The branch was created from a stale base.

**Classification: divergent against shippability.** The branch needs to be rebased onto current `main` so the diff shrinks to the actual fix (one comment block in `agent.py` plus the test). In its current shape, maintainer first impression is "bot dump" regardless of the fix's correctness.

**Edge.** Rebuild the branch from current `main`:
1. `git fetch upstream && git checkout main && git pull`
2. `git checkout -b fix-aclose-race-clean`
3. Cherry-pick or hand-apply only the `agent.py` and `tests/test_engine/test_aclose_race.py` changes.
4. Force-push (operator decision) over the existing branch, **or** open a fresh PR and close #21.

---

## Graph state

| Node | Status | Shape | Note |
|------|--------|-------|------|
| H₀ — fix prevents RuntimeError on the patched path | partial | convergent | Structurally plausible; not validated end-to-end |
| H₁ — regression test fails on master | **killed** | divergent against | Test only asserts a timeout exception both branches raise |
| H₂ — fix addresses ab2ence's specific symptom | partial | convergent | Orphan-task framing in traceback not fully explained |
| H₃ — sibling `_close_provider_stream` calls safe | confirmed | convergent | No action |
| H₄ — PR shape ships as-is | killed | divergent against | Stale branch, CONFLICTING, 16k LOC unrelated drift |

## Frontier edges

1. Rewrite the regression test to genuinely fail on master (capture orphan-task warning via `loop.set_exception_handler`, or assert that the generator's `finally` was *not* re-entered).
2. Reproduce ab2ence's exact traceback locally to confirm the patched path is the producing path. If not, find the real producing site.
3. Rebase `fix-aclose-race` onto current `main` to shrink the PR to the targeted change.

## Reasoning mode table

| Claim | Mode | Confidence |
|-------|------|------------|
| Test does not fail on master | Deduction (read the test, both branches raise same exception) | 95% |
| PR is 16k LOC drift on a 1-line fix | Induction (counted file list from `gh api`) | 99% |
| Diagnosis structurally plausible | Deduction (traced `__anext__` cancellation semantics) | 80% |
| Orphan-task framing unexplained | Abduction (traceback mentions a Task; patched path doesn't create one) | 70% |
| Sibling callsites safe | Deduction (control-flow read) | 95% |

## Pruning log

- **H₁ killed.** Test reads as a regression test but isn't one. This is the dominant finding — without a test that fails on master, shipping the fix is shipping unverified.
- **H₄ killed.** PR will be closed for shape before review reaches the fix.

---

## H₅ — The stated race does not occur in the test's own scenario (2026-05-18 follow-up)

**Hypothesis** (PR's mechanism). On master, with the PR's exact
`_generator_with_slow_cleanup` (yields after sleep(1.0); finally sleeps 0.05)
and a 10ms iter deadline, `await next_event` returns while the generator's
finally is still running, so the subsequent `_close_provider_stream` collides
with that running cleanup and raises `RuntimeError: aclose(): asynchronous
generator is already running`.

**Null.** `await next_event` waits for the cancellation to propagate fully —
including the finally's `await asyncio.sleep(0.05)` — so when it returns the
generator's frame is gone and `aclose()` short-circuits to a no-op.

**Perturbation.** Replayed the master-side branch in isolation against the same
toy generator at 10ms deadline. Captured `ag_running` and `ag_frame` between
`await next_event` and `_close_provider_stream`, and installed
`loop.set_exception_handler` to count unretrieved task exceptions.

**Result.**
```
after await next_event: ag_running=False, ag_frame=None
timeout raised OK
unretrieved exceptions: 0
```

The generator is fully finalized before `_close_provider_stream` runs. No
RuntimeError is raised — not even one that the `except Exception` in
`_close_provider_stream` would suppress. The stated race does not occur in the
shipped test's scenario.

**Classification: divergent against the PR's stated mechanism.** Combined with
H₁ (test's single assertion passes on master), the test is doubly inert: not
only does it not assert the right thing, the wrong thing it doesn't assert also
doesn't happen.

**Where ab2ence's traceback probably comes from.** The reporter's fingerprint
`async_generator_athrow` + "Task exception was never retrieved" is the classic
signature of CPython's async-generator GC finalizer hook: when an async
generator is dropped mid-iteration, asyncio schedules `aclose()` as a Task on
the loop. If at that moment the generator is busy (e.g., a wrapper's `finally`
is still draining), the scheduled `aclose()` Task raises "already running" and
is GC'd without `.result()`. Candidate sites in this repo:

- `engine/stream_wrappers.py:163-167` (`heartbeat_stream` finally — cancels the
  pending `__anext__` task, awaits it, but the outer generator can be dropped
  before this completes during multi-agent shutdown).
- `engine/stream_wrappers.py:106` (`asyncio.wait_for(aiter.__anext__(), ...)` in
  `idle_timeout_stream` — under shutdown cancel, the inner aiter can be left
  for GC to finalize).

Neither path is touched by this PR.

**Edge.** Before merging, instrument the multi-agent auto-stop scenario
ab2ence describes and capture which call site creates the orphan
`async_generator_athrow` task on master. If it's in `stream_wrappers.py`, the
PR closes a different (possibly imaginary) defect than the one it claims to
fix, and #14 stays open.

## Updated graph state

| Node | Status | Shape |
|------|--------|-------|
| H₀ — fix prevents RuntimeError on the patched path | partial | convergent |
| H₁ — regression test fails on master | **killed** | divergent against |
| H₂ — fix addresses ab2ence's specific symptom | **partial / unlikely** | divergent |
| H₃ — sibling `_close_provider_stream` calls safe | confirmed | convergent |
| H₄ — PR shape ships as-is | killed | divergent against |
| H₅ — stated race reproduces in the PR's own test scenario | **killed** | divergent against |

## Updated recommendation

The earlier two blockers (rebase + rewrite test) stand. H₅ adds a third
concern that supersedes the others on substance: **the comment the PR adds to
`agent.py` lines 1960-1962 names a mechanism that does not occur in the test
the PR ships with**. Either find a scenario where the race genuinely fires
(then the comment is true and the test should exercise it), or rewrite the
comment + PR body to "redundant cleanup removal; cancellation already drains
the generator," drop the "Fixes #14" claim, and open a separate investigation
into `stream_wrappers.py` shutdown to actually address ab2ence's symptom.

## Recommendation (Phase 8 — human gate)

**Do not ship as-is.** Two blocking issues:

1. **Rebase the branch** onto current `main` so the diff is the actual fix.
2. **Rewrite the test** so it genuinely fails on master. Capture either the orphan-task warning via `loop.set_exception_handler`, or detect re-entry of the generator's `finally` directly. The current test passes on master and is misleading.

Optional, lower priority:
3. Reproduce ab2ence's exact traceback on master to confirm the patched site is the producing site (vs. an unrelated `athrow` orphan elsewhere). If the patched site doesn't reproduce the warning, the fix may close a real defect but not the one #14 reports.
