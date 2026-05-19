# Hypothesis graph: VictoriaMetrics/helm-charts#2894

**Issue:** Service generated for vlstorage/vlinsert/vlselect uses hardcoded port name `http` and the `servicePort` value from `values.yaml`, regardless of what the user sets via `extraArgs.httpListenAddr`. User changed `vlstorage.extraArgs.httpListenAddr: ":9429"` (for mTLS); the rendered Service still binds port `9491` with name `http`.

## H₀ — observation

The container's port is derived from `extraArgs.httpListenAddr` (vlstorage-server.yaml:60: `containerPort: {{ include "vm.port.from.flag" ... }}`), and its name is `$app.ports.name | default "http"`. The Service's `name`, `port`, and `targetPort` are not. They live in three ports templates in `_helpers.tpl`:

- `vlselect.ports` (line 92): hardcoded `name: http`, `port: $service.servicePort`, `targetPort: $service.targetPort`
- `vlinsert.ports` (line 107): same shape
- `vlstorage.ports` (line 122): hardcoded `name: http`, `port: $service.servicePort`, `targetPort: http` (string literal)

**Trajectory: divergent.** The container/Service mismatch is structural — when `httpListenAddr` is overridden, the container moves but the Service does not. Reproduced by reading user's attached values file (httpListenAddr `:9429`, no `service.servicePort` override).

## H₁ — fix shape (deduction, 95% conf)

In the three ports templates, derive `port` from `extraArgs.httpListenAddr` (default to `$service.servicePort`) — the same `vm.port.from.flag` helper already used by the StatefulSet/Deployment containerPort and by `vm.host` in `_service.tpl`. Use `$app.ports.name | default "http"` for both the port `name` and `targetPort`, matching what the container exposes.

When `httpListenAddr` is at its default (the values.yaml default), `vm.port.from.flag` returns the address's port (e.g. `9491`) which equals `$service.servicePort` — snapshot tests stay green.

## Provenance check

- `vlstorage-server.yaml:58-60` already follows this pattern for the container — applying the same shape to the Service is the obvious mechanical alignment, not a new design.
- `_service.tpl:55` uses the same `vm.port.from.flag` shape with `$port` as default — the maintainer pattern is established.
- `vmauth.ports` (line 136) has the same hardcoded shape as vlstorage but vmauth is out of scope for this issue; flagging as a follow-up frontier edge.

## Frontier edges

- `vmauth.ports` has the same shape — same bug class, not reported. Left untouched; the issue is narrowly about vlogs cluster.
- Could also wire `service.servicePort` defaults to be empty so the derivation always wins, but that's a riskier values.yaml schema change. Out of scope.

## Phase 5.5 — regression check

Snapshot tests in `tests/__snapshot__/service_test.yaml.snap` render default-port Services at `port: 9491/9471/9481`, `name: http`, `targetPort: http`. With the fix and default values, `vm.port.from.flag` extracts `9491` from `:9491`, and `ports.name` defaults to `http`. Snapshots stay identical.

## Phase 8 — ship

Minimal patch to three port templates in `charts/victoria-logs-cluster/templates/_helpers.tpl`. Tests should remain unchanged.
