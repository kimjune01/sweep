# hyperium/h2 #882 — RecvStream::is_end_stream() never true; data() never returns None

**Issue**: After local cancel (SendStream dropped without END_STREAM) and remote END_STREAM, `RecvStream::data()` infinitely yields `Err(Reset(_, NO_ERROR, Remote))` and `is_end_stream()` stays `false`.

**Maintainer hint** (seanmonstar): "because it was a _local_ reset, it keeps returning it instead of remembering you've seen the cancel error already."

## H₀ — Baseline (deduction from code read)

- **Hypothesis**: `RecvStream::poll_data` returns the same error indefinitely because the stream's `state.ensure_recv_open()` returns `Err(e.clone())` on every poll once the state is `Closed(Cause::Error(_))`.
- **Perturbation**: trace `share.rs:412 data() -> streams.rs:1439 poll_data -> recv.rs:1187 poll_data -> recv.rs:1232 schedule_recv -> state.rs:433 ensure_recv_open`.
- **Evidence**:
  - `state.rs:433-443` `ensure_recv_open()` for `Closed(Cause::Error(ref e))` returns `Err(e.clone())` — pure read, no state mutation. Every call returns the same Err.
  - `recv.rs:1237` `if stream.state.ensure_recv_open()? { ... }` — the `?` short-circuits and converts `Err(e)` into `Poll::Ready(Some(Err(e.into())))` via the FromResidual impl on `Poll<Option<Result<_,_>>>`.
  - `state.rs:413-416` `is_recv_end_stream()` returns `true` only for `Closed(Cause::EndStream) | HalfClosedRemote(_)`. Both the local-reset state (`Closed(Cause::Error)` with `is_local()`) and the remote-reset-after-local-cancel state are excluded, so `is_end_stream()` always returns `false` after cancel.
- **Trajectory**: divergent (root cause located). Status: **confirmed**.

## H₁ — Why only the local-reset path observably loops

- **Hypothesis**: Pure remote-reset streams (peer sends RST_STREAM with no local cancel) hit the same `Closed(Cause::Error)` branch but users hit it less because typical code drops `RecvStream` on the first `Err`. The bug is general; the reporter happens to keep polling, exposing the infinite loop.
- **Provenance**: `state.rs:258 recv_reset` writes `Closed(Cause::Error(Error::remote_reset(...)))` — same state class as the local-cancel path. So `ensure_recv_open` will also yield Err repeatedly in that path. **Same bug, not a separate code path.** Confirms the fix should target `schedule_recv` / `is_end_stream`, not the cancel path specifically.

## H₂ — Fix shape

Two coordinated edits, no new state on `Stream`:

1. **`recv.rs::schedule_recv`** — after delivering the error once, subsequent polls must return `Poll::Ready(None)`. Cheapest implementation: have `schedule_recv` consume the `Cause::Error` once and overwrite the state with `Closed(Cause::EndStream)` (or a new "delivered" marker) after returning the error. Cleaner alternative: don't mutate state; add a `recv_err_delivered: bool` on `Stream` and check it before re-querying `ensure_recv_open`.
2. **`state.rs::is_recv_end_stream`** — broaden to include any `Closed(_)` state (so the docstring on `RecvStream::is_end_stream` — "calls to poll … will return None" — actually holds after the fix to (1)).

**Preferred shape** (minimal, no new field, no extra state-machine surface):

```rust
// recv.rs::schedule_recv  (replacement)
fn schedule_recv<T>(
    &mut self,
    cx: &Context,
    stream: &mut Stream,
) -> Poll<Option<Result<T, proto::Error>>> {
    match stream.state.ensure_recv_open() {
        Ok(true) => {
            stream.recv_task = Some(cx.waker().clone());
            Poll::Pending
        }
        Ok(false) => Poll::Ready(None),
        Err(e) => {
            // Deliver the error once, then transition so subsequent polls
            // return Ready(None) and is_end_stream() returns true.
            stream.state.set_recv_closed_after_error();
            Poll::Ready(Some(Err(e)))
        }
    }
}
```

```rust
// state.rs — new helper; transitions Closed(Cause::Error) -> Closed(Cause::EndStream)
pub fn set_recv_closed_after_error(&mut self) {
    if matches!(self.inner, Closed(Cause::Error(_)) | Closed(Cause::ScheduledLibraryReset(_))) {
        self.inner = Closed(Cause::EndStream);
    }
}
```

With this, `is_recv_end_stream()` already covers `Closed(Cause::EndStream)`, so option (2) above is not needed.

## Risk

- Overwriting `Closed(Cause::Error)` with `Closed(Cause::EndStream)` could change other observers (`is_local_error`, `is_reset`, `is_remote_reset`, `ensure_reason`). Need to verify no live code path on a *closed* stream reads those *after* `poll_data` has consumed it. Audit list:
  - `is_local_error` — used in `recv.rs::recv_data` (line 651) to ignore frames after local reset. That's checked BEFORE `poll_data` would have run on a user-facing stream; the reset bookkeeping for the wire path happens elsewhere. Verify.
  - `is_remote_reset` — used in `poll_reset` machinery; user-facing.
  - `ensure_reason` — used by `poll_reset`. If a user holds both `RecvStream` and a `Reset` future, calling `poll_data` before `poll_reset` could lose the reason. Mitigation: use the alternate "`recv_err_delivered` flag" shape instead of mutating state.

**Safer alternate fix** (preferred if the audit surfaces any reader of the error post-consumption):

```rust
// Stream gains:  pub recv_err_delivered: bool

// schedule_recv
if stream.recv_err_delivered {
    return Poll::Ready(None);
}
match stream.state.ensure_recv_open() {
    Ok(true) => { ... Pending }
    Ok(false) => Poll::Ready(None),
    Err(e) => { stream.recv_err_delivered = true; Poll::Ready(Some(Err(e))) }
}

// is_end_stream (in recv.rs:633) — extra OR clause
pub fn is_end_stream(&self, stream: &store::Ptr) -> bool {
    if stream.recv_err_delivered && stream.pending_recv.is_empty() {
        return true;
    }
    if !stream.state.is_recv_end_stream() {
        return false;
    }
    stream.pending_recv.is_empty()
}
```

This shape preserves the error state for `poll_reset` callers while making `poll_data` idempotent post-error.

## Test (fail-on-master, pass-on-fix)

Add an integration test under `tests/h2-tests/tests/`: client sends headers without END_STREAM, server sends a complete response with END_STREAM, client drops its `SendStream`. Loop on `body.data()`:
- master: returns `Err(Reset(_, NO_ERROR, _))` indefinitely; `is_end_stream()` stays false.
- fix: returns `Some(Err(_))` at most once, then `None`; `is_end_stream()` becomes true.

Bound the test loop (e.g. 5 polls) so a regression shows as a clear failure, not a hang.

## Status

- H₀ **confirmed** (deduction, code-read, 95% confidence)
- H₁ **confirmed** as scope-clarifying (deduction, 90%)
- H₂ **proposed**, alternate shape preferred pending audit (abduction, 75%)
- Next: implement preferred fix, write failing test, run repo tests, then Phase 7 bug-hunt.

## Frontier

- Audit `is_local_error / is_remote_reset / ensure_reason` consumers to choose between the two fix shapes.
- Confirm `body.data()` infinite-loop reproduces in a unit test (`extract.py` analog) before shipping.
