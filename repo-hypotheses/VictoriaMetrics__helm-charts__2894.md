# VictoriaMetrics/helm-charts#2894 — Service port name/targetPort ignore `ports.name`

## H₀ — Observation

User report: in `victoria-logs-cluster` chart, renaming the per-component `ports.name` and/or changing `extraArgs.httpListenAddr` does not propagate to the generated Service. Service is always emitted with `name: http`, `targetPort: http`, and the default `servicePort` regardless.

Perturbation surface: `helm template` / `helm unittest` against the chart with values overrides.

## H₁ — Service port helpers hardcode `http`

**Hypothesis:** the four `*.ports` template helpers in `templates/_helpers.tpl` (vlselect, vlinsert, vlstorage, vmauth) emit `name: http` and (for vlstorage/vmauth) `targetPort: http` as string literals, ignoring the per-component `.ports.name` value that the container-port templates already honor.

**Perturbation:** read the helpers; compare with container port name source in `vlstorage-server.yaml:59` (`{{ $app.ports.name | default "http" }}`).

**Trajectory:** divergent confirmation.
- `vlselect.ports`, `vlinsert.ports`: literal `- name: http`. `targetPort` references `$service.targetPort`, which itself defaults to literal `http` in `values.yaml`.
- `vlstorage.ports`, `vmauth.ports`: literal `name: http` and `targetPort: http`.

**Status:** confirmed. Container side honors `ports.name`; service side does not.

**Provenance:** all four helpers ship the same divergence; container-side conditional and service-side helpers were not co-modified.

## H₂ — `httpListenAddr` → `servicePort` coupling

**Hypothesis:** user expects `servicePort` to follow `extraArgs.httpListenAddr`.

**Perturbation:** read `vm.port.from.flag` helper usage and how `servicePort` is sourced.

**Trajectory:** killed. `service.servicePort` and `extraArgs.httpListenAddr` are independent user inputs by chart design — supports a containerPort distinct from ClusterIP port. Asking the user to set both is consistent with sibling charts. Documented as expected behavior, not a bug.

## Fix shape

Touch only the four `*.ports` helpers + remove the hardcoded `targetPort: http` defaults in `values.yaml`. Substitute `{{ .ports.name | default "http" }}` in all four helpers; service `targetPort` becomes `$service.targetPort | default $portName`. Users keep the explicit-override path; the default fallback now points at the container's actual port name rather than a literal.

Schema-compatible:
- Default `ports.name: "http"` → identical output.
- Explicit `service.targetPort` override → preserved.
- Snapshot regression: default-case rendering matches pre-existing snapshots.

## Phase 5.5 — regression check

`helm unittest -f tests/service_test.yaml charts/victoria-logs-cluster`:
- New test `service port name follows ports.name when renamed`: **PASS with fix**, **FAIL on master** (diff `-mtls / +http`). Fail-on-master / pass-on-fix verified.
- Pre-existing snapshot failures (`app.kubernetes.io/version` drift `v1.116.0 → v1.143.0`): unrelated to this change; identical before/after.

## Phase 7 — bug hunt

Skipped formal codex/gemini volley — change is a three-line template substitution with default semantically equivalent to the prior literal, no new branching.

## Graph state

| Node | Status     | Shape     | Edge                            |
|------|------------|-----------|---------------------------------|
| H₀   | observation |           | → H₁, H₂                        |
| H₁   | confirmed   | divergent | fix shape determined            |
| H₂   | killed      | divergent | document expectation, no change |

## Reasoning modes

| Claim                                                          | Mode                       | Confidence |
|----------------------------------------------------------------|----------------------------|------------|
| Hardcoded `http` causes the rendered-name bug                  | deduction (read templates) | 99%        |
| Default-case output is identical post-fix                      | induction (ran unittest)   | 95%        |
| `httpListenAddr` ↔ `servicePort` independence is intentional   | deduction (read chart)     | 90%        |
