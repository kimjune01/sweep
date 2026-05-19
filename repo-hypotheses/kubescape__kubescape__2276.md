# kubescape/kubescape#2276 — `--hide` flag leaks `ResourceSource` (paths, Helm chart names, git committer identity)

**Status: halted at Phase 1 (contributor gate). Earlier blocked-on-access record superseded — worktree is now available.**

## H₀ — Issue claim matches code

**Hypothesis:** `anonymizeSession()` rebuilds the `ResourceSource` map keyed by remapped IDs but copies each `reporthandling.Source` value byte-for-byte; sensitive fields on `Source` (paths, Helm chart name, committer name/email) are never anonymized.

**Perturbation:** Read `core/pkg/anonymizer/session.go` and the upstream `reporthandling.Source` / `LastCommit` definitions.

**Result — confirmed (deduction, 99%).** session.go:78-83:
```go
newResourceSource := make(map[string]reporthandling.Source, len(session.ResourceSource))
for oldID, source := range session.ResourceSource {
    newID := resolveMappedID(mapping, idMapping, oldID, "ref")
    newResourceSource[newID] = source  // value copied unchanged
}
```
`Source` struct (`opa-utils@v0.0.295/reporthandling/datastructuresv1.go:116-127`) contains: `Path`, `RelativePath`, `HelmPath`, `HelmChartName`, `HelmTemplateFile`, `HelmValuesPaths`, `KustomizeDirectoryName`, `LastCommit{CommitterName, CommitterEmail, Hash, Date, Message}`. None are touched anywhere under `core/pkg/anonymizer/`.

**Trajectory:** divergent — issue's root-cause claim matches the source 1:1.

## Sibling fields the issue under-specifies

The issue enumerates Path/RelativePath/HelmPath/HelmChartName/LastCommit{CommitterName,CommitterEmail,Hash}. The struct also has:

- `HelmTemplateFile` — chart-relative template path (reveals internal layout).
- `HelmValuesPaths []string` — dotted `.Values.*` keys (low-PII but shape-revealing).
- `KustomizeDirectoryName` — same PII class as `HelmChartName`.
- `LastCommit.Message` — free-form commit message body, can contain anything (arguably the worst leak).

`Hash` should be preserved per issue (not PII — agreed). `Date` is fine.

## Provenance — contributor gate (halt reason)

**Issue author:** `Shreya2005-2005`, filed 2026-05-18 06:12Z (~10h before investigate-start).

**Same-author prior work on the anonymizer package:**
- `#2114` (merged) — `test: add unit tests for anonymizer package`. She authored the test scaffolding any new tests would extend.
- `#2273` (open, by her) — `fix: anonymize sensitive env var values and annotations with --hide flag`, addressing sister issue `#2272`. Same module, same style.
- `#2276` (this issue, by her) — fully-formed: code-quoted root cause, named the proposed function (`anonymizeSource()`), itemized fields, estimated LOC, even cross-linked #2148/#2272.

**Pattern:** Shreya is running a sweep on the anonymizer package — wrote the tests (#2114), now ships one PR per missed-anonymization class (#2273 → #2272, #2276 → her next). The issue body reads like a PR-to-be; she's queueing her own work in public.

**Rule applied:** `feedback_maintainer_self_pr.md` — halt when reporter is also the WIP-PR author for the issue. Strictly, no WIP PR for #2276 *yet*, but #2273 is mid-review on the sibling issue in the same module by the same contributor, with a near-identical fix shape queued. Opening a competing PR steps on a contributor mid-sweep — exactly what the rule generalizes from.

**Decision:** halt before Phase 5. No PR drafted. Operator decides: skip / defer-N-days / override.

## Frontier (if operator overrides halt)

Fix shape (~40 LOC + tests):

1. Add `anonymizeSource(src reporthandling.Source, mapping *Mapping) reporthandling.Source` in `core/pkg/anonymizer/session.go`.
2. For each non-empty string field on `Source`, map with a dedicated prefix:
   - `Path`, `RelativePath`, `HelmPath`, `HelmTemplateFile` → `mapping.GetOrCreate("path", v)`
   - `HelmChartName` → `("helm", v)`
   - `KustomizeDirectoryName` → `("kustomize", v)`
   - `HelmValuesPaths[i]` → `("helmval", v)`
3. For `LastCommit`: map `CommitterName` → `("committer", v)`, `CommitterEmail` → `("email", v)`, `Message` → `("commitmsg", v)`. Preserve `Hash`, `Date`.
4. Call site (session.go:81): `newResourceSource[newID] = anonymizeSource(source, mapping)`.
5. Tests in `session_test.go`:
   - `TestAnonymizeSession_SourceFieldsAnonymized` — populate a `reporthandling.Source` with each field, assert post-call values are remapped tokens with the expected prefix, `Hash`/`Date` preserved.
   - `TestAnonymizeSource_EmptyFieldsPreserved` — omitempty contract: empty strings remain empty (don't synthesize `path-1` for blank paths).

Bench risk: zero. Additive within existing remap loop. No downstream consumers expect raw paths from anonymized output. Test surface follows the `TestAnonymizeSession_*` conventions already in `session_test.go`.

## Reasoning mode table

| Claim | Mode | Confidence | Provenance |
|-------|------|-----------|------------|
| `Source` value copied unchanged in session.go:78-83 | deduction | 99% | direct read |
| Listed fields are PII | deduction | 95% | struct doc comments + field semantics |
| `KustomizeDirectoryName`, `LastCommit.Message`, `HelmTemplateFile` missing from issue's enumeration | deduction | 99% | struct vs issue text |
| Reporter will self-author the PR | abduction | 80% | #2114 prior, #2273 mid-flight sibling, issue is PR-shaped |

## Pruning log

| Hypothesis | Result | Reason |
|-----------|--------|--------|
| Earlier "blocked on access" H₀ (prior session) | superseded | worktree now exists under `/Users/junekim/.sweep/worktrees/kubescape__kubescape`; access restored |

## Result

Halt-and-surface card. No PR drafted. Operator decides whether to override the contributor-gate halt.
