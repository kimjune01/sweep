# hyperium/tonic#2586 — Issue when combining with tonic-rest

**Status:** halt — design call, not bug fix. Route to maintainer judgment.

## H₀ — Reporter framing

> `tonic-web/src/service.rs:111` should pass through HTTP/1 non-grpc-web requests to the inner service (mirroring the HTTP/2 branch at line 101) so REST routes can coexist with `GrpcWebLayer`.

Currently: HTTP/1 non-grpc-web → `BAD_REQUEST`. HTTP/2 non-grpc-web → passthrough.

## H₁ — Asymmetry is a deliberate design choice (confirmed)

**Perturbation:** read `tonic-web/src/service.rs` and surrounding context.

**Evidence:**
- Code path at `tonic-web/src/service.rs:101-117` explicitly distinguishes the two: HTTP/2 → `Case::Other { future: inner.call(req) }`; HTTP/1 → `Case::immediate(StatusCode::BAD_REQUEST)`.
- Doc comment lines 99-100: *"All http/2 requests that are not grpc-web are passed through to the inner service, whatever they are."* — HTTP/1 deliberately gets the opposite treatment.
- Rationale: HTTP/2 is gRPC's native transport, so multiplexing other H2 traffic (e.g. axum routes) on the same port is a documented pattern. HTTP/1 reaching a grpc-web service was historically *only* browser grpc-web; non-grpc-web H1 was treated as protocol error.

**Trajectory:** divergent — the asymmetry is intentional, not an oversight.

## H₂ — Maintainer prefers compose-at-router, not transparent-layer (confirmed via #1964)

**Perturbation:** read issue #1964 (similar tonic-web + axum composition question).

**Evidence:**
- Maintainer `tottoto` direct quote: *"There isn't need to get `Routes` via `Router`. It can be built directly."*
- Reporter `repnop`'s working solution: wrap `GrpcWebLayer` *only around the gRPC server*, then add it to `tonic::service::Routes` / axum router that also holds non-grpc routes.
- Pattern: `GrpcWebLayer` is scoped to grpc-web traffic; cross-protocol routing is the router's job, not the layer's.

**Trajectory:** divergent — the project's idiom for "grpc-web + REST" is router-level composition, not making the layer transparent.

## H₃ — Reporter's setup is a layer-scope mistake, fixable in user code (confirmed)

In the snippet:
```rust
Server::builder()
    .accept_http1(true)
    .layer(tonic_web::GrpcWebLayer::new())      // applied to the WHOLE server
    .add_routes(proto::rest::proto_rest_router(...).into())
```

`.layer(GrpcWebLayer)` wraps every route, including REST. The fix is to scope the layer to the grpc service only, e.g. via `Routes::builder().add_service(GrpcWebLayer::new().layer(svc))` or by wrapping individual gRPC services rather than the whole router. That matches the #1964 resolution.

**Trajectory:** divergent — bug is in user composition, not the layer.

## H₄ — Changing line 111 to passthrough is semantically risky (open, not pursued)

If we *did* change `RequestKind::Other(_) =>` to passthrough:
- Existing users layering `GrpcWebLayer` directly over a single tonic gRPC service would now forward malformed HTTP/1 traffic into a service that can't handle it. Behavior shifts from "clean 400" to "downstream undefined" (likely 502/hang/panic depending on inner service).
- The 400 currently functions as a documented protocol guard. Removing it is a silent semantic break for the dominant deployment shape.
- No second user has reported the friction; no maintainer has signaled this asymmetry is wrong.

This is a maintainer-only call. Not pursued.

## Reasoning mode table

| Node | Mode | Confidence |
|------|------|------------|
| H₁ asymmetry intentional | Deduction (read code + comments) | 95% |
| H₂ maintainer prefers router-compose | Induction (read #1964 thread) | 90% |
| H₃ user-fixable in composition | Deduction (read snippet) | 85% |
| H₄ passthrough is risky | Abduction | 70% |

## Decision

**Halt, do not ship a PR.** This is not a bug — it is:
1. An intentional asymmetry in `GrpcWebLayer` (H₁).
2. A composition mistake in the reporter's user code, with an established fix idiom (H₂, H₃).
3. Any code change to line 111 is a semantic break that only the maintainer should authorize (H₄).

The right artifact would be a comment pointing the reporter at the #1964 pattern (scope `GrpcWebLayer` to the grpc service, multiplex at the router level). That's a `comment-issue` task, not an `investigate` → PR task.

## Frontier (closed)

No open edges. No experiments left to run without maintainer input.
