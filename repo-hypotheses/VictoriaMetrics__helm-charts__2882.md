# VictoriaMetrics/helm-charts#2882 — Operator admissionWebhooks Aren't Working As Expected

**Report:** user installs `victoria-metrics-operator` chart v0.62.1. A `VMAgent` manifest containing a non-existent field (`test: true`) is accepted by the cluster. With the upstream `install-with-webhook.yaml` from the operator repo, the same manifest is rejected.

## Diagnosis

The bad manifest is silently pruned/accepted because the helm chart, by default, installs **specless CRDs** — every CRD's `spec.spec` schema is just `{ type: object, x-kubernetes-preserve-unknown-fields: true }`. The kube-apiserver's strict field validation (which is what actually rejects `test: true` in the upstream manifest) is bypassed: with `preserveUnknownFields: true` every key under `spec.*` is allowed.

The webhook **is** running and reachable; the webhook config that helm renders is wired correctly (path, port, CA, service all match what the operator expects). The webhook just doesn't catch this kind of error: the VMAgent validator (`internal/webhook/operator/v1beta1/vmagent_webhook.go`) only checks `obj.Status.ParsingSpecError` (empty at CREATE time) and `obj.Validate()` (typed struct validation — unknown fields were already dropped by the JSON decode). It has no way to see `test: true`.

The upstream `install-with-webhook.yaml` works because it ships the **full** openAPIV3Schema (~3000 lines per CRD). The apiserver's structural schema check rejects unknown fields under `spec` before the webhook ever runs.

## Why the chart is shaped this way

- Commit `0f6a51d19f` / PR [#2419](https://github.com/VictoriaMetrics/helm-charts/pull/2419) made the templated CRDs specless on purpose, to fix #2420: the full schema pushed the helm release Secret over 1 MiB (`Too long: may not be more than 1048576 bytes`) and broke upgrades.
- The full strict CRDs are available via the `crds` subchart, gated on `crds.plain: true`. That path uses a kubectl-apply Job (init container `bzcat` of `crd.yaml.bz2`) to install CRDs server-side instead of through helm-managed manifests, dodging the 1 MiB limit.

## Workaround for users

Set:

```yaml
crds:
  plain: true
admissionWebhooks:
  enabled: true
```

With `crds.plain: true`, the operator chart short-circuits its specless `templates/crd.yaml` (see `{{- if and (not .Values.crds.plain) .Values.crds.enabled }}` guard) and lets the `crds` subchart deliver the full schema via an upgrade Job. Apiserver-side strict validation then rejects unknown fields like `test: true` without any webhook involvement.

Note: the subchart's `upgrade.enabled` is also `false` by default; users likely need `crds.upgrade.enabled: true` as well for the Job to actually run.

## Hypothesis graph

### H₀ — webhook config malformed (path/port/CA wrong)

- **Perturbation:** render the chart, compare each webhook entry to upstream `install-with-webhook.yaml`.
- **Result:** path scheme matches (`/validate-operator-victoriametrics-com-<version>-<singular>`). Port is `9443` (explicit) vs upstream omits (defaults 443) — but the helm Service exposes port 9443 → targetPort `webhook` (=9443 in deployment). CA is self-generated and inlined; cert dir matches operator default `/tmp/k8s-webhook-server/serving-certs`. ObjectSelector excludes `app.kubernetes.io/name = victoria-metrics-operator`; a user-applied VMAgent without that label still matches `NotIn` (label-selector semantics: missing key satisfies NotIn).
- **Trajectory:** convergent — the webhook IS reachable.
- **Status:** killed. Wiring isn't the issue.
- **Mode:** deduction (read the rendered manifest, compared to upstream).

### H₁ — operator webhook validator only checks known fields

- **Perturbation:** read `internal/webhook/operator/v1beta1/vmagent_webhook.go`.
- **Result:** `ValidateCreate` returns based on `obj.Status.ParsingSpecError` (not set at create) and `obj.Validate()` (typed struct validation). At decode time, unknown JSON fields not in the Go struct are silently dropped — webhook can't see `test: true`.
- **Trajectory:** divergent (against "webhook can catch this"). Webhook is structurally incapable of catching unknown fields.
- **Status:** confirmed.
- **Mode:** deduction.

### H₂ — specless CRD allows unknown fields through

- **Perturbation:** extract VMAgent CRD from helm `crd.yaml` vs `install-with-webhook.yaml`. Compare schema for `.spec.versions[].schema.openAPIV3Schema.properties.spec`.
- **Result:**
  - Helm chart (templated path): 107 lines for VMAgent CRD; `spec: { type: object, x-kubernetes-preserve-unknown-fields: true }`.
  - Upstream install-with-webhook: 3096 lines for VMAgent CRD; full property list, no preserveUnknownFields.
- **Trajectory:** divergent (for the diagnosis). With `preserveUnknownFields: true`, apiserver structural-schema rejection doesn't fire on unknown keys under `spec`.
- **Status:** confirmed root cause.
- **Mode:** induction (compared the actual rendered CRDs).

### H₃ — chart provides an opt-in to the strict CRDs

- **Perturbation:** inspect `templates/crd.yaml` and `Chart.yaml`. Trace the `crds.plain` flag.
- **Result:** `crds.plain: true` disables the specless templated CRDs AND enables the `crds` subchart (gated by `condition: crds.plain`), which ships `crds/crd.yaml` containing the full 3000-line schema per CRD and applies via a kubectl Job.
- **Trajectory:** convergent — the chart already has the right escape hatch, it's just not the default.
- **Status:** confirmed.
- **Mode:** deduction.

### H₄ — default flip would regress #2420 (>1 MiB helm release Secret)

- **Perturbation:** read PR #2419 and issue #2420.
- **Result:** specless was a deliberate fix for the helm release Secret hitting 1 MiB. Flipping the default back to plain CRDs in `templates/crd.yaml` would resurrect that bug.
- **Trajectory:** divergent against "just change the default". The subchart path (kubectl Job applying CRDs out of helm's Secret) is the only safe way to ship the full schema, and it has its own UX cost (extra Job, extra ServiceAccount).
- **Status:** confirmed — there's no clean default flip.
- **Mode:** deduction (read the prior PR + issue).

## Graph state

| Node | Status | Shape | Mode |
|------|--------|-------|------|
| H₀ webhook wiring wrong | killed | convergent | deduction |
| H₁ webhook can't see unknown fields | confirmed | divergent | deduction |
| H₂ specless CRD preserves unknown fields | confirmed (root cause) | divergent | induction |
| H₃ `crds.plain: true` opt-in exists | confirmed | convergent | deduction |
| H₄ default flip would regress #2420 | confirmed | divergent | deduction |

## Reframe

Original framing: "admissionWebhooks aren't working". Actual finding: webhooks **are** working as designed; the cluster's structural schema validation isn't, because the templated CRDs are deliberately specless to fit under helm's 1 MiB Secret cap. The webhook layer was never the right place to catch unknown-field errors — that's the CRD schema's job.

## Verdict

No fix to ship. The behavior is a documented trade-off: chart maintainers picked "small helm releases" over "strict schema by default". Users who want strict validation should set `crds.plain: true` and `crds.upgrade.enabled: true`. A README/values.yaml note clarifying that field-validation strictness depends on `crds.plain` would help future users hit this less, but that's a docs-only nit and not a behavioral bug.

→ Route to tissue (report findings, no PR).
