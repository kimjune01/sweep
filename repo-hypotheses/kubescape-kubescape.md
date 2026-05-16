# Triage Graph: kubescape/kubescape

Scanned: 2026-05-09
Stars: ~11K | Language: Go | License: Apache-2.0

## Repo Culture

- Active maintainer: **matthyx** (Matthias Bertschy) -- reviews PRs, triages issues, responsive
- Secondary: **slashben** -- handles cloud/EKS-specific issues
- PR density: moderate (13 open PRs). Several from repeat contributors (Shreya2005-2005, manmathbh)
- Gate: CI must pass. Maintainer review required. Bug fixes merge; features need discussion first.

## Selected: #2075 -- Vulnerability manifest resource URIs rejected due to incorrect URI splitting

- **Type:** bug (labeled)
- **Filed:** 2026-05-09 by harshakumar25
- **Competing PRs:** none
- **Root cause:** `ReadResource` in `cmd/mcpserver/mcpserver.go` splits the full `kubescape://vulnerability-manifests/...` URI on `/`, producing 6 parts (scheme, empty, authority, path segments). Code expects 4-5 parts, so every valid request is rejected.
- **Fix:** Extract `parseVulnManifestURI` helper that strips the prefix before splitting (matching the pattern already used in `ReadConfigurationResource`). Added segment-level validation (action must be `cve_list` or `cve_details`, rejects empty namespace/manifest/CVE ID).
- **Review gates:** codex (pass, round 1), gemini (pass, round 1). Both confirmed fix is correct. Codex suggested extracting helper + tightening validation; applied. Gemini confirmed logic correctness, noted pre-existing `null` vs `[]` JSON issue (out of scope).
- **Branch:** `fix/vulnerability-manifest-uri-parsing`
- **Commit:** `45eddf44`

## Evaluated and Rejected

| # | Title | Reason |
|---|-------|--------|
| 2007 | Support Multiple Output Formats | feature, help wanted -- Mujib-Ahasan actively claimed and in discussion with maintainer |
| 2028 | IDOR / Data Leak in results lookup | bug -- harshakumar25 actively working, maintainer approved plan |
| 2065 | "Loaded exceptions" success log on failure | bug -- yugal07 already raised PR |
| 2068 | goroutine leak in patchWithContext | Shreya2005-2005 already has PR #2070 |
| 2071 | findFile swallows errors | Shreya2005-2005 already has PR #2072 |
| 2073 | Test coverage for ResultsHandler | Varadraj75 already has PR #2074 |
| 1959 | C-0066 false positive on EKS | Fix is in regolibrary repo, not kubescape |
| 1912 | EKS region failure | Windows-specific, needs reproduction environment |
| 2010 | Surface scan coverage | feature -- active discussion, PR #2069 exists |
| 2066 | Docs: grammatical error | Shreya2005-2005 already has PR #2067 |
| 1819 | Upgrade OPA to v1 | Large dependency migration, 19 comments, complex |
| 1818 | Harbor integration | feature, help wanted -- 25 comments, design not settled |

## Hypothesis Coverage

- **H0 (cold bug fix merges):** #2075 is a clean bug fix with no competing PRs. Highest merge probability.
- **H1 (AI-friendly flood):** Moderate PR density from repeat contributors, but maintainer is responsive and engaged. Not flooded.
- **H2 (feature vs fix):** Confirmed: bug fixes merge, features need discussion. Selected accordingly.
