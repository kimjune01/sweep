# goharbor/harbor Triage Graph

**Repo**: goharbor/harbor (CNCF container registry, 28K stars, Go + Angular)
**Scanned**: 2026-05-09
**Lead issue**: #18329 (API sort by repo_count) -- contested, PR #23081 open since 2026-04-09

## Issue Scan

### Good First Issues (2 open)

| Issue | Title | Status | Competing PR | Decision |
|-------|-------|--------|-------------|----------|
| #18329 | Cannot Sort Projects by repo_count or owner_name | Assigned to chlins | #23081 (muratclk, open 2026-04-09) | Skip -- contested |
| #18340 | Show Raw yaml File on UI under Helm Values Tab | Assigned to zyyw, AllForNothing | None | Skip -- original requester says no longer needed |

### Bugs Scanned (kind/bug)

| Issue | Title | Competing PR | Decision |
|-------|-------|-------------|----------|
| #23115 | Copy Artifact link not working | #23174 (varsha-0007) | Skip -- contested |
| #22878 | Unredacted secrets in operation logs | #22879 (marevers) | Skip -- contested |
| #22675 | Handle Redis errors in connection limiter | #22679 (Tusharjamdade, changes requested) | Skip -- contested |
| #17443 | Listing artifacts in non-existing repo returns 200 | #17618 (3 years stale, internal disagreement) | Skip -- political |

### Uncontested Issues Found

| Issue | Title | Type | Filed By | Decision |
|-------|-------|------|----------|----------|
| #23218 | Remove temporary SBOM permission override | Bug fix / cleanup | rakshityadav1868 | **Selected** |
| #23149 | Repository update_time not updated | Bug | wy65701436 (maintainer) | Skip -- self-assigned maintainer task |

## Selected: #23218

**Problem**: `artifact-list-page.service.ts` has `this._hasSbomPermission = true;` that overrides the actual permission check result. The TODO comment says "need to remove the static code." Introduced by maintainer Wang Yan in commit 461a5fa50d during SBOM feature development (PR #20200). Bypasses RBAC for SBOM operations.

**Fix**: Remove the 2-line override (comment + assignment). Add test verifying permission denial propagates correctly.

**Branch**: `fix/remove-sbom-permission-override`
**Files**: 2 changed (+13/-2)
- `artifact-list-page.service.ts`: Remove override
- `artifact-list-page.service.spec.ts`: Add SBOM-permission-denied test

**Risk**: Low. The override was explicitly marked temporary. The correct permission path (line 196) was already in place but dead. Existing test passes unchanged because it mocks all permissions as true.

## Observations

- Harbor has very few uncontested good-first-issues. Most bugs attract multiple contributors.
- Maintainer engagement pattern: `bupd` (member) gates contributions, `wy65701436` and `chlins` do reviews.
- DCO sign-off required on all commits.
- Convention: `fix(scope): description` commit format, PR must reference issue with `Fixes #N`.
- This is a first contribution. Bug fix, minimal diff, clear provenance. Follows the bug-fixes-merge heuristic.

## Reinvestigate cycle 2026-05-18 (PR #23223)

**Failing checks**: `Check release-note label set` (FAILURE), `codecov/project` (FAILURE).

**H_ci_label**: CI fails because the PR carries no `release-note/*` label.
- Perturbation: read failing job log -- `mheap/github-action-required-labels@v5` with `labels: release-note/.*`, `Found: ` (empty).
- Trajectory: divergent confirmation. The action is a label gate, not a code gate.
- Kill condition: try to add `release-note/update` via `gh pr edit`. Result: `GraphQL: kimjune01 does not have the correct permissions to execute AddLabelsToLabelable`.
- **Confirmed**: external contributors cannot self-apply labels on goharbor/harbor. Only a maintainer with triage rights can satisfy this check.

**H_ci_codecov**: `codecov/project` listed FAILURE.
- Perturbation: read codecov comment -- "All modified and coverable lines are covered by tests. Project coverage is 66.03%."
- Trajectory: convergent benign. Project-level threshold drift, not a fix-side regression. Unblocks when maintainer overrides or merges other coverage-raising PRs.

**Edge**: no code change available. Both failures are maintainer-side gates (label assignment, codecov project threshold). Status quo: @chlins already pinged @bupd for review on 2026-05-11. Halt -- nothing to push.

**Reasoning mode**: deduction (CI log read directly) + induction (gh edit attempt refuted by API).
