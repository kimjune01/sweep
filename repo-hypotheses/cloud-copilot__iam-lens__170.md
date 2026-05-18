# Hypothesis Graph: cloud-copilot/iam-lens#170

Date: 2026-05-18
Worktree: `/Users/junekim/.sweep/worktrees/cloud-copilot__iam-lens`
Canonical test env: `docker:sweep-tester:latest`
Canonical test command: `npx vitest --run --coverage`

## Issue Context

Local `gh issue view` could not reach `api.github.com`, and the web cache did not expose the issue body. The checked-out branch is `add-iam-group-support-principal-can`; the investigation treats issue #170 as "add IAM group support to `principal-can`" unless later evidence contradicts it.

## Graph State

| Node | Status | Trajectory | Summary |
| --- | --- | --- | --- |
| H0 | partial | divergent | `principal-can` previously accepted users/roles/sessions but not IAM group ARNs; current branch adds group detection and policy loading but lacks a behavioral `principal-can` test. |
| H1 | confirmed | divergent | Added an end-to-end `principalCan()` integration case for a group fixture with an inline identity policy. |
| H2 | confirmed | divergent | Reviewer found a synthetic-principal counterexample: resource-policy simulation can match `aws:PrincipalArn` to a group ARN, which AWS never emits for real requests. |
| H3 | partial | convergent | Verification is blocked in this sandbox: Docker daemon access is denied and local `node_modules` are absent. |
| H4 | confirmed | divergent | The fix shape is identity-policy-only early return for group ARNs, with an impossible resource-policy fixture guarding the regression. |
| H5 | confirmed | divergent | Group early return must preserve normal allow-minus-deny output semantics, not emit unrelated denies directly. |

## Nodes

### H0: `principal-can` needs group support

- Hypothesis: issue #170 asks for `principal-can` to accept IAM group ARNs and report the group's identity-based permissions.
- Null: group support is already complete, or the branch name is misleading.
- Perturbation: inspect branch diff against `origin/main`, CLI help, `src/principals.ts`, and existing tests.
- Evidence: branch adds `isIamGroupArn()`, `getAllPoliciesForGroup()`, dispatch from `getAllPoliciesForPrincipal()`, docs/CLI text, and parser tests. It does not add an integration test proving `principalCan()` returns group policies.
- Trajectory shape: divergent from "complete fix"; implementation intent is present, but validation stops before the main command behavior.
- Kill condition: an end-to-end test for a group principal passes on main and branch without any code change.
- Edge: add a behavioral test using existing collected group fixtures, then run it against the branch.
- Reasoning mode: deduction from diff and tests, confidence 95%.

### H1: behavioral coverage is the decisive perturbation

- Hypothesis: an integration test for `principalCan()` on an IAM group ARN will expose whether the branch is complete.
- Null: unit tests around ARN classification are sufficient because `principalCan()` uses the shared policy loader exactly like users/roles.
- Perturbation: add a `principalCanIntegration` case for a group fixture with managed and/or inline policies.
- Predicted trajectory shape: divergent; either output matches expected permissions and H1 confirms, or it fails and generates the next edge.
- Kill condition: no suitable fixture exists, or group fixtures cannot be loaded by `IamCollectClient`.
- Edge: inspect `src/test-datasets` and `IamCollectClient` group methods.
- Reasoning mode: abduction from missing test surface, confidence 80%.

### H2: resource-policy paths must not treat groups as principals

- Hypothesis: because IAM groups cannot appear as principals in resource-based policies, `principalCan()` should evaluate only group identity policies plus org policy constraints, not direct bucket/KMS/trust resource allows.
- Null: passing a group ARN through resource-policy helper functions is harmless because none of those helpers will match groups.
- Perturbation: trace `s3BucketsSameAccount`, `kmsKeysSameAccount`, `iamRolesSameAccount`, and cross-account bucket checks for group input.
- Predicted trajectory shape: oscillatory; identity policies are valid for groups, but resource-policy augmentation may be semantically wrong if any helper matches account-level principals.
- Kill condition: helpers only add resource allows on exact principal matches that cannot match group ARNs, or existing semantics deliberately include account-level resource policies for any same-account identity.
- Edge: trace helper matching logic before changing production code.
- Reasoning mode: abduction from AWS IAM semantics, confidence 70%.

#### H2 Result

- Perturbation: traced `s3BucketsSameAccount`, `s3BucketsCrossAccount`, `kmsKeysSameAccount`, `iamRolesSameAccount`, and `statementAppliesToPrincipal`.
- Evidence: a second-pass reviewer identified that `statementAppliesToPrincipal()` builds a simulation request with `principal: groupArn`, which can synthesize principal context such as `aws:PrincipalArn = arn:aws:iam::acct:group/Developers`. A resource policy using `Principal: "*"` plus an `aws:PrincipalArn` condition matching that group ARN can return `PrincipalMatch` and be added by S3/KMS/role helpers, even though AWS request context never uses a group ARN as the authenticated principal.
- Trajectory shape: divergent against the prior "harmless" interpretation.
- Status: confirmed.
- Edge generated: `principalCan()` must treat group ARNs as identity-policy containers and skip resource-policy augmentation paths.
- Reasoning mode: deduction from reviewer trace and AWS docs, confidence 95%.

### H3: verification environment gap

- Hypothesis: the integration test is sufficient, but it cannot be executed in this sandbox.
- Null: canonical or host tests are runnable.
- Perturbation: run canonical Docker command and inspect local test dependencies.
- Evidence: `docker run ... sweep-tester:latest npx vitest --run src/principalCan/principalCanIntegration.test.ts` fails with Docker socket permission denied; `node_modules/.bin/vitest` is absent. `npx prettier` attempted to resolve from `registry.npmjs.org` and failed with `ENOTFOUND`. `codex exec` also fails to initialize its local app-server client, so codex filtering is unavailable.
- Trajectory shape: convergent; the branch can be statically checked and diffed here, but runtime verification must happen in QA/CI or a less restricted local shell.
- Kill condition: Docker socket access is restored or dependencies are installed.
- Edge: mark verification gap in PR/readiness notes and do not overclaim a passing test run.
- Reasoning mode: induction from command results, confidence 95%.

### H4: group `principal-can` should be identity-policy-only

- Hypothesis: for a group ARN, `principalCan()` should build the consolidated policy from policies attached to that group and return before KMS, IAM role trust, S3 bucket, cross-account, SCP/RCP principal-condition simulation, and other resource-policy paths.
- Null: group ARNs can safely be passed to resource-policy helpers because impossible direct group principals never match.
- Perturbation: implement an early return after `allowedPermissions` and `identityDenyPermissions`; add a test group fixture with an inline `ec2:DescribeInstances` allow and a same-account bucket policy that would match only if the simulator synthesized `aws:PrincipalArn` as the group ARN.
- Evidence: production diff imports `isIamGroupArn` in `src/principalCan/principalCan.ts` and returns `toPolicyStatements(allowedPermissions)` plus `toPolicyStatements(identityDenyPermissions)` before resource-policy augmentation. The integration test expects only `ec2:DescribeInstances`, so the `s3:ListBucket` bucket policy fixture is a regression tripwire.
- Trajectory shape: divergent in favor of the fix shape.
- Kill condition: maintainer intended group output to model a hypothetical member principal rather than the group policy container. Current CLI/docs wording says the opposite: identity-based policies only.
- Edge: run `npx vitest --run src/principalCan/principalCanIntegration.test.ts` in the canonical Docker env when available.
- Reasoning mode: deduction from code plus reviewer counterexample, confidence 93%.

### H5: group output must use existing deny subtraction semantics

- Hypothesis: an identity-policy-only group path still needs the normal `principal-can` allow-minus-deny behavior.
- Null: direct emission of all identity denies is acceptable for group output.
- Perturbation: second-pass review of the early return against `PermissionSet.subtract()` and `docs/PrincipalCan.md`.
- Evidence: existing docs say non-overlapping deny statements are dropped because `principal-can` focuses on what the principal can do. The initial early return emitted all identity denies directly, so a group with `Allow ec2:DescribeInstances` and unrelated `Deny s3:DeleteObject` would report an irrelevant deny. The fix now calls `allowedPermissions.subtract(identityDenyPermissions)` and emits only the resulting allow/deny sets.
- Trajectory shape: divergent against the first early-return implementation.
- Status: confirmed and fixed.
- Edge: fixture now includes a disjoint group deny while the expected output remains only the EC2 allow.
- Reasoning mode: deduction from local docs/code, confidence 96%.

## Provenance

- `getAllPoliciesForPrincipal()` was introduced by David Kerber in `4644814` (`feat: Simulate requests on the CLI`, 2025-05-26). Group policy collection methods on `IamCollectClient` date to David Kerber commits `3a8989f`/`0b82808` in May-June 2025, and group inline policy validation was touched in `3a30c0b` on 2025-07-22.
- The group-dispatch branch work is local commits `b5de1a2` (`feat: Add IAM group support to principal-can command`) and `f2bfc4b` (`fix: Add null checks and improve error handling for group ARNs`), authored 2026-05-11.
- Upstream issue/PR search: local `gh` could not connect to `api.github.com`; web search found no indexed same-repo PR/issue for `principal-can` group support. AWS docs confirm the main semantic constraint: groups can receive identity-based policies but cannot be specified as resource-policy principals.
- Risk assessment: this appears to connect an existing overlooked mechanism (`IamCollectClient` group policy loaders) to `principal-can`, not a new evaluator path. The remaining risk is unexecuted integration verification in this sandbox.

## Frontier Edges

| Edge | Perturbation | Predicted Classification | Confidence |
| --- | --- | --- | --- |
| E1 | Add group guard around resource-policy augmentation and test fixture with direct group-shaped bucket policy | Divergent | 90% |
| E2 | Run added group `principalCan()` integration test in QA/CI | Divergent | 85% |
| E3 | Check for duplicate upstream PR when GitHub API is reachable | Convergent | 75% |
| E4 | Add managed-policy group fixture if maintainer wants broader coverage | Convergent | 70% |

## Reasoning Modes

| Claim | Mode | Confidence |
| --- | --- | --- |
| The branch adds parser/loader support for group ARNs. | Deduction | 95% |
| The current tests do not prove `principal-can` group behavior. | Deduction | 95% |
| Resource-policy handling is a production-code blocker for group support unless group ARNs bypass those helpers. | Deduction | 95% |
| The new integration test should fail on `origin/main` because group ARNs hit `Unsupported principal type`. | Deduction | 95% |
| The implemented early return matches the branch's identity-policy-only group semantics. | Deduction | 93% |
| Emitting all group identity denies directly would regress documented `principal-can` output semantics. | Deduction | 96% |

## Pruning Log

- Earlier H2 interpretation pruned: reviewer counterexample showed synthetic group principal context can over-add impossible resource-policy permissions.
