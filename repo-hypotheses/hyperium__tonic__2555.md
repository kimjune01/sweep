# hyperium/tonic#2555 — Client panic in hand-rolled `Grpc::unary`

## H₀ (observation)
User calls `Grpc::new(channel).unary(...)` without first awaiting `.ready()`. Channel (a `tower::Buffer`) panics in `Buffer::call`:
> `send_item` called without first calling `poll_reserve`

Stack: `Grpc::streaming` → `<Channel as Service>::call` → `Buffer::call` → `PollSender::send_item` panic.

## H₁ (deduction, killed→confirmed)
Tower contract requires `poll_ready` → `Ready(Ok(()))` before each `call`. `tonic/src/client/grpc.rs:312` invokes `self.inner.call(request)` directly; no `poll_ready` upstream of it inside `streaming`. The only readiness primitive offered on `Grpc<T>` is the public `Grpc::ready` (grpc.rs:199) which the user must call themselves.

**Verification (deduction, ~99%):** `tonic-build/src/client.rs:240,271,302,333` emits `self.inner.ready().await.map_err(...)?` immediately before each `unary`/`server_streaming`/`client_streaming`/`streaming` call. Generated clients never hit this. Hand-written clients that mirror the API surface miss the readiness contract because it isn't documented on the send methods — only on the separate `ready()` method.

## H₂ (alternative, killed)
"Auto-await ready inside `streaming`." Tested mentally: would double-call `poll_ready` for every codegen-generated client. `PollSender::poll_reserve` is idempotent once a permit is held, so it's not a deadlock — but it expands the public Service-contract surface (e.g. `Status` vs `T::Error` mapping) and silently masks misuse of arbitrary user `GrpcService` impls that aren't idempotent. Killed: doc fix has smaller blast radius and matches maintainer precedent (#545: "user must call ready first; PR to fix examples welcome").

## Provenance check
- `Grpc::ready` and the codegen `ready().await` pattern have been the explicit contract since at least v0.4 (#545, 2021-01-27, davidpdrsn). Treated as user error then; user was directed to fix examples.
- No newer issue/PR proposes auto-readiness. No competing fix in flight.

## Surviving fix
Documentation patch on the four send methods (`unary`, `client_streaming`, `server_streaming`, `streaming`) — a `# Panics` section noting the Tower readiness requirement and pointing to `Grpc::ready`. One short example showing the `ready().await?` call before `unary`.

## Reasoning modes
- H₀: induction (panic reproduced in user's reported run)
- H₁: deduction (read codegen + grpc.rs)
- H₂: deduction (Tower/Buffer semantics)

## Edge / next perturbation
Land doc patch; no test (doc-only). CI = build + doctest.
