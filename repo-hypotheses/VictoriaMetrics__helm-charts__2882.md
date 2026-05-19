# VictoriaMetrics/helm-charts#2882 — admissionWebhooks accept malformed manifests

## H₀ (observation)
Helm chart's admission webhooks accept malformed VMAgent manifests (e.g. `spec.test: true`); upstream `install-with-webhook.yaml` from the operator release rejects the same input. Both ship the same operator binary (v0.70.0).

## H₁ — webhook routing broken in chart (KILLED, deduction)
**Perturbation**: `helm template charts/victoria-metrics-operator/`; diff rendered Service/Deployment/ValidatingWebhookConfiguration against upstream `install-with-webhook.yaml`.

- Webhook path `/validate-operator-victoriametrics-com-v1beta1-vmagent` matches upstream.
- Service port 9443 → targetPort `webhook` (containerPort 9443). Plumbing is fine.
- TLS cert SANs cover `<svc>.<ns>.svc` and `.svc.<cluster.dnsDomain>`.
- `failurePolicy: Fail`, so an unreachable webhook would *reject*, not accept. The manifest being accepted proves the webhook is reachable and returns "allow".

Trajectory: divergent against. Webhook plumbing is correct.

## H₂ — operator's validator doesn't see unknown fields (CONFIRMED, deduction)
**Perturbation**: read `internal/webhook/operator/v1beta1/vmagent_webhook.go@v0.70.0`.

```go
func (*VMAgentCustomValidator) ValidateCreate(_ context.Context, obj *vmv1beta1.VMAgent) {
    if obj.Status.ParsingSpecError != "" { return ..., errors.New(...) }
    if err := obj.Validate(); err != nil { return ..., err }
    return nil, nil
}
```

Validator runs on a parsed Go struct. Unknown JSON fields (`test: true`) are dropped by `json.Unmarshal` before the validator sees them. The webhook **cannot** catch unknown-field errors on the protocol level — it operates after apiserver→struct decode.

## H₃ — chart ships specless CRDs; upstream ships full schema (CONFIRMED, induction)
**Perturbation**: compare CRDs.

| Source | VMAgent CRD `spec` schema |
|---|---|
| `charts/victoria-metrics-operator/crd.yaml` (default, `crds.plain: false`) | `{"required":["remoteWrite"],"type":"object","x-kubernetes-preserve-unknown-fields":true}` — **specless** |
| `charts/victoria-metrics-operator/charts/crds/crds/crd.yaml` (when `crds.plain: true`) | Full `properties:` schema, no preserve-unknown-fields. 45,807-line file. |
| Upstream `install-with-webhook.yaml` | Full `properties:` schema. |

With `x-kubernetes-preserve-unknown-fields: true` and no `properties`, the **apiserver itself** accepts any field under `spec`. There is no schema-level rejection.

Upstream rejects `test: true` at the **apiserver layer**, before the webhook runs, via CRD-pruning. The webhook is incidental for this failure mode.

**Provenance**: helm-charts PR #2419 ("operator: make templated crds specless"), merged 2025-09-27. Closed #2420 and #2334 (rendering perf issues). Deliberate tradeoff: apiserver-side schema validation for chart-render speed.

## Diagnosis
The chart's default-mode (`crds.plain: false`) ships specless CRDs that disable apiserver-side schema validation. The admission webhook validates a Go struct, which silently drops unknown JSON keys. So malformed manifests slip through.

`install-with-webhook.yaml` includes full-schema CRDs; apiserver rejects unknown fields before the webhook runs.

Setting `crds.plain: true` (or pre-applying upstream CRDs) restores rejection. Workaround already available; no chart bug in the routing sense.

## Candidate fixes

1. **Doc fix (low risk)**: clarify in `values.yaml` and README that `crds.plain: false` ships specless CRDs and that admission webhooks alone do not reject unknown fields; recommend `crds.plain: true` (or applying the upstream CRD bundle) for strict validation.
2. **Default flip to `crds.plain: true`**: re-introduces the rendering perf hit PR #2419 explicitly chose to avoid. Needs maintainer signoff.
3. **Specless-but-strict**: drop `x-kubernetes-preserve-unknown-fields: true` from the specless CRD. Apiserver would then reject **all** spec fields (no properties defined). Breaks valid manifests. Not viable.

## Recommendation
Halt at diagnosis. The fix is a tradeoff only the maintainer can pick.

- Option (1) is a one-paragraph doc clarification.
- Option (2) reverses the explicit decision in PR #2419 and needs maintainer judgment.
- Option (3) is structurally impossible.

Substrate shouldn't ship "a fix" that papers over a deliberate design decision. Route to operator for a yes/no on PRing option (1).

## Reasoning mode table
| Claim | Mode | Confidence |
|---|---|---|
| Webhook routing is correct | deduction (rendered manifests) | 98% |
| Webhook can't see unknown JSON fields | deduction (Go source) | 99% |
| Chart's specless CRDs accept unknown fields; upstream's full CRDs don't | deduction (schema comparison) | 99% |
| PR #2419 was a deliberate perf tradeoff | deduction (PR description) | 95% |

## Frontier (open)
- Live verify in `kind` that `crds.plain: true` restores rejection (untested; pure inference).
- Confirm v0.62.1 (user's version) ships the same specless CRDs as v0.63.0 — almost certainly yes; PR #2419 merged well before v0.62.1.
