# Hypothesis graph: stacklok/docs-website#866

**Issue:** Document `baselineClientScopes` on `MCPExternalAuthConfig` embedded auth server.

## H₀ — The requested documentation is missing from the repo.

- **Null:** the docs already exist; the issue is stale.
- **Perturbation:** grep the worktree for `baselineClientScopes`, `embeddedAuthServer`, and "Baseline scopes for DCR clients".
- **Result:**
  - `docs/toolhive/concepts/embedded-auth-server.mdx` lines 148–167 contain a dedicated "Baseline scopes for DCR clients" section covering: what the field does, the Claude Code DCR scope-narrowing motivating scenario, RFC 7591 framing, recommended values (`openid`, `offline_access`), and the warning against privileged scopes.
  - `docs/toolhive/guides-k8s/auth-k8s.mdx` line 554 lists `baselineClientScopes` in the `MCPExternalAuthConfig` configuration reference table with a deep link to the concept doc's `#baseline-scopes-for-dcr-clients` anchor.
- **Trajectory shape:** divergent against. The docs are present, comprehensive, and cross-linked.
- **Kill condition:** H₀ refuted.
- **Edge:** ask when the docs landed and whether the issue should be closed.

## H₁ — Provenance: when and how did the docs land?

- **Perturbation:** `git log -S baselineClientScopes` against the worktree.
- **Result:** PR [#867](https://github.com/stacklok/docs-website/pull/867) — "Update stacklok/toolhive to v0.27.2" — merged 2026-05-13. Commit message lists three relevant subjects: "Document baselineClientScopes for embedded auth server", "Polish baselineClientScopes editorial pass", "Fix baselineClientScopes validation description". Authored alongside the Renovate bump that pulled in toolhive v0.27.2 (the release that shipped the field via toolhive#5233).
- **Trajectory:** divergent — PR #867 is the resolution.
- **Edge:** the PR did not include a `Closes #866` trailer (closingIssuesReferences is empty in the gh API), which is why the issue remained open after merge.

## H₂ — Coverage gap check against the issue's "What's needed" list.

| Requirement | Status | Where |
|---|---|---|
| What `baselineClientScopes` does + RFC 7591 framing | covered | concept doc lines 148–162 |
| Canonical motivating scenario (Claude Code, narrowed DCR `scope`, `invalid_scope` at `/oauth/authorize`) | covered | concept doc lines 150–154 |
| When to set it (`openid`, `offline_access`; no privileged scopes) | covered | concept doc lines 164–167 |
| Worked example with a complete `MCPExternalAuthConfig` of `type: embeddedAuthServer` showing the field in context | **partial** — the operator guide's worked example (auth-k8s.mdx lines 501–543) does not include `baselineClientScopes` in the YAML body; the field is only described in the reference table at line 554 | guide YAML vs reference table |
| Cross-link to the auto-generated CRD reference in toolhive's `docs/operator/crd-api.md` | not present in either doc; the concept doc links to the guide and vice versa, but neither links to toolhive's `docs/operator/crd-api.md` | both docs |

- **Trajectory:** convergent — most asks are met; two minor gaps remain (a YAML-body inclusion and a CRD-reference cross-link).

## H₃ — Should an additional PR be filed for the gaps?

- **Pushout consideration:** the Claude Code scenario is already the load-bearing motivation, and the reference-table entry plus deep link to the concept doc give a reader who lands on the guide enough to act. The YAML body inclusion is a nice-to-have; the missing CRD cross-link is a real gap, but the toolhive CRD reference lives in a separate repo and the docs site does not link directly to it from this page today.
- **Trajectory:** chaotic — value of a second PR is low, friction is non-zero (maintainer attention, drip queue slot), and the original requester (jhrozek) may judge the existing coverage sufficient.
- **Recommended action:** do **not** open a new PR. Surface findings to the issue author via a side-hatch tissue comment that (a) confirms the substantive ask landed in #867, (b) notes the two minor coverage gaps so the maintainer can decide whether to close or keep open as a "polish" follow-up.

## Graph state

| Node | Status | Shape |
|---|---|---|
| H₀ docs missing | killed | divergent against |
| H₁ provenance | confirmed | divergent |
| H₂ coverage gap | partial | convergent (two minor gaps) |
| H₃ open new PR | killed | chaotic — low value |

## Frontier

Closed. Routing to **/tissue** — operator approves wording; no PR.

## Reasoning mode table

| Claim | Mode | Confidence |
|---|---|---|
| Docs already exist | induction (grep + read) | 99% |
| PR #867 added them | deduction (git log + commit message) | 99% |
| Issue remained open because of missing `Closes #` trailer | deduction (gh closingIssuesReferences empty) | 95% |
| Two minor gaps remain (YAML body, CRD cross-link) | induction (file read) | 95% |
| A second PR is not worth the friction | abduction | 70% — operator may disagree |
