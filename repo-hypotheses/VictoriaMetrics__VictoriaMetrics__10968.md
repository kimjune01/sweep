# VictoriaMetrics #10968 — federate ignores `escaping=allow-utf-8`

## H₀ — `/federate` never inspects the Accept header

- **Mode:** deduction (read `FederateHandler` + `federate.qtpl`)
- **Perturbation:** grep `app/vmselect/prometheus/prometheus.go` for `Accept`, `escaping`, `allow-utf-8`. None present in the federate handler. The only `Accept`-aware logic in the package is unrelated CORS.
- **Trajectory:** divergent — handler unconditionally writes `text/plain; charset=utf-8` then calls `WriteFederate` regardless of request headers.
- **Status:** **confirmed.**
- **Kill condition:** any reference to Prometheus content-negotiation (`escaping=…`) found in federate path. None found.

## H₁ — `prometheusMetricName` always emits unquoted-name + `name{…}` order

- **Mode:** deduction (read `app/vmselect/prometheus/export.qtpl:158-171`)
- **Perturbation:** read template.
  ```
  {%z= mn.MetricGroup %}
  {% if len(mn.Tags) > 0 %}{
      {%z= tags[0].Key %}={%= escapePrometheusLabel(tags[0].Value) %}
      …
  }{% endif %}
  ```
- **Trajectory:** divergent — name is always emitted as raw bytes outside the braces. There is no branch that emits the Prometheus-3.0 quoted form `{"name", k="v"}`.
- **Status:** **confirmed.**

## H₂ — PR #8692 added UTF-8 ingest/parse but not federate output

- **Mode:** deduction (changelog + template grep)
- **Perturbation:** the federate template hasn't been touched since long before the UTF-8 work; `app/vmselect/prometheus` has no helper that switches between legacy and quoted-name output. The bug-report's own context line matches.
- **Trajectory:** convergent — issue framing matches code state. Closes H₂ as background; not a new edge.
- **Status:** **confirmed.**

## Diagnosis

Two missing pieces:
1. The federate handler does not parse the request `Accept` header to decide on escaping scheme.
2. The metric-name writer cannot emit the Prometheus 3.0 quoted-name form (`{"my.metric", k="v"} 1 12345`) for non-legacy names.

Both are needed for an OTel-compliant scraper to consume `/federate` for dotted metric names.

## Fix shape

- New helper file `app/vmselect/prometheus/federate_utf8.go`:
  - `acceptsUTF8MetricNames(r *http.Request) bool` — scans `Accept` header for `escaping=allow-utf-8` (case-insensitive token in any media-range parameter list).
  - `isLegacyName(b []byte) bool` — `^[A-Za-z_:][A-Za-z0-9_:]*$` (mirrors `model.LegacyValidation.IsValidMetricName`).
  - `writeFederateLineUTF8(bb, rs)` — emits the federate line; if the metric name is legacy AND all label keys are legacy, uses the existing format; otherwise emits the `{"name", key="val", …}` form, escaping non-legacy keys with the same `"…"` wrapping per Prometheus 3.0.
- `FederateHandler` (`prometheus.go`): if `acceptsUTF8MetricNames(r)`, write each row via the new helper; otherwise keep the existing `WriteFederate` hot path untouched.
- Test (`federate_utf8_test.go`): construct an `mn` with metric group `api.total_2xx_rq` and a legacy tag; call the new helper; assert the bytes equal the quoted form. The same input passed through the existing `WriteFederate` produces the unquoted form — the test pins both behaviors so regressions surface.

## Provenance

- Reference implementation: `vendor/github.com/prometheus/common/expfmt/text_create.go:360-457` (`writeName` + quoted-name branch). Same shape; we won't take a runtime dep on `expfmt` because the federate hot path writes via `quicktemplate` for a reason.
- `model.LegacyValidation.IsValidMetricName` and `EscapingScheme` enum live in the already-vendored `prometheus/common/model` — we could call them, but reimplementing the 15-line legacy-name check avoids reaching into vendored validators from a hot path.

## Frontier edges

- E1 — Should we also support `escape-utf-8` value variants (`escaping=values`, `escaping=underscores`, `escaping=dots`)? **Not in scope.** The issue is specifically about `allow-utf-8`; the other escaping schemes mutate names instead of preserving them, and VM does not currently mutate names server-side at query time. Note in PR body as follow-up.
- E2 — Does `/api/v1/export` need the same treatment? Likely yes, but the issue scopes to `/federate`; leave for a separate PR.

## Reasoning modes

| Claim | Mode | Confidence |
|---|---|---|
| Federate handler ignores Accept | deduction (code read) | 0.98 |
| `prometheusMetricName` only emits unquoted | deduction | 0.98 |
| Quoted form is the correct fix shape | abduction from upstream Prometheus reference | 0.9 |
| Backward compat preserved (no Accept = no change) | deduction | 0.95 |
