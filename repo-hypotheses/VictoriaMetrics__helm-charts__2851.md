# VictoriaMetrics/helm-charts#2851 — StatefulSet VCT immutability for `server.persistentVolume.size`

**Status:** halt at observation. Maintainer explicitly stated no chart-level workaround exists; the only contributable surface is documentation, and the maintainer did not ask for docs either.

## H₀ — The chart can avoid the VCT-immutable error on size change

- **Null:** the chart already mitigates this.
- **Perturbation:** read `charts/victoria-logs-single/templates/server.yaml:177-194`. The `volumeClaimTemplates` block hard-renders `storage: {{ $pvc.size }}` whenever `persistentVolume.enabled` and no `existingClaim` is set. There is no conditional that omits the size on upgrade (Helm templates can't know upgrade-vs-install without `lookup`, and `lookup` is unreliable under ArgoCD + `--dry-run`).
- **Trajectory:** divergent against. Kubernetes' StatefulSet API forbids VCT mutation; the only chart-side options would be (a) switching to a separately-managed PVC (breaks the StatefulSet pod-identity guarantee) or (b) `lookup`-based conditional rendering (unreliable). Both are invasive structural changes the maintainer would not accept casually.
- **Maintainer signal:** AndrewChubatiuk 2026-04-27T17:14:47Z — "there're no other workarounds besides one you've mentioned… alternatively you can try operator's VLSingle, which supports storage size upgrade". Confirms (a) and (b) are off the table; the limitation is accepted.
- **Edge killed → H₁.**

## H₁ — A docs note on `size` is the only contributable surface

- **Null:** docs are sufficient already.
- **Perturbation:** read `charts/victoria-logs-single/values.yaml:191-192`:
  ```yaml
  # -- Size of the volume. Should be calculated based on the logs you send and retention policy you set.
  size: 10Gi
  ```
  The comment describes only the sizing heuristic. No mention that the value is effectively immutable post-install or that `kubectl patch pvc` + cascade-orphan `StatefulSet` delete is required to resize. The README is auto-generated from these comments (cf. commit `6759ec7 Automatic update CHANGELOGs and READMEs`), so editing the values.yaml comment propagates to README on next maintainer rebuild.
- **Trajectory:** convergent — the gap is real, the fix is one comment block.
- **Same gap exists** in `charts/victoria-metrics-single/values.yaml:212` (identical pattern). Out of scope for this issue's PR; would invite scope-creep review.

## H₂ — Maintainer would accept an unsolicited docs PR

- **Null:** maintainer files the issue and moves on; an unsolicited docs PR is noise.
- **Evidence for:**
  - Reporter's "expected behavior" explicitly offered docs as an acceptable resolution.
  - Issue is still open (not closed as wontfix).
  - The chart already documents one-liner caveats elsewhere (`# -- StorageClass to use… If defined, PVC created automatically`).
- **Evidence against:**
  - Maintainer gave reason-can't with no ask. Per [[feedback_maintainer_comment_register]], that is closer to "no further action" than "PRs welcome."
  - No prior PRs by kimjune01 on this repo; first-impression PR should be unambiguously wanted.
- **Trajectory:** oscillatory. The fix is tiny and helpful but unsolicited; risk of being declined as noise.
- **Edge → human gate (Phase 8).** Do not push speculatively.

## Frontier

- E₁: ship a 3-line comment extension on `values.yaml:191` for `victoria-logs-single` only. Predicted classification: convergent-accept ~55%, polite-decline ~30%, ignored ~15%.
- E₂ (out of scope, do not bundle): same edit for `victoria-metrics-single`. Bundling would convert a tiny doc-fix into a multi-chart PR that triggers heavier review.

## Reasoning modes

| Claim | Mode | Confidence |
|---|---|---|
| StatefulSet VCT is immutable | deduction (k8s API spec) | 99% |
| Chart hard-renders size into VCT | deduction (read template) | 99% |
| README auto-generated from values.yaml | induction (commit history) | 95% |
| Maintainer would accept docs PR | abduction (issue tone) | 55% |

## Decision

Halt at Phase 4. Surface the proposed docs change to the operator before any push. The investigation does not justify autonomous ship; the maintainer-comment register puts this in human-attendable territory.
