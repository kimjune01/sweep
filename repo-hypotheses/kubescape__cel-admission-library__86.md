# Hypothesis Graph: kubescape/cel-admission-library#86

Started: 2026-05-18
Task: `kubescape/cel-admission-library#86`
Canonical worktree from `sweep project-info`: `/Users/junekim/.sweep/worktrees/kubescape__cel-admission-library`
Canonical test environment: `docker:sweep-tester:latest`

## Issue Context

Cached triage attestation: `/Users/junekim/.sweep/attestations/triage/kubescape__cel-admission-library__86.md`

Triage title: `C-0038 workload expression checks hostIPC but reads hostPID, allowing unsafe workload specs`

Triage summary: issue reports a likely copy-paste bug at `controls/C-0038/policy.yaml:29`, where the workload expression checks `hostIPC` but reads `hostPID`. Proposed fix shape is a single-field swap. Triage says existing tests reportedly cover the scenario.

## H0: Perturbation Surface Exists

Hypothesis: The repository checkout is available locally, so the policy and tests can be poked directly.

Null: The canonical worktree is absent and network access is unavailable; there is no local perturbation surface.

Perturbation:
- Ran `sweep project-info kubescape/cel-admission-library`.
- Attempted `gh issue view 86 --repo kubescape/cel-admission-library`.
- Attempted `git ls-remote https://github.com/kubescape/cel-admission-library.git HEAD`.
- Searched `/Users/junekim/Documents/sweep` and `/Users/junekim/.sweep` for cached `cel-admission-library`/`kubescape__cel-admission-library` checkouts.

Observation:
- `project-info` reports `worktree_exists: false`.
- `gh issue view` failed with `error connecting to api.github.com`.
- `git ls-remote` failed DNS resolution for `github.com`.
- Local search found only the triage attestation and no repository checkout.

Trajectory shape: Divergent against H0.

Kill condition: If the canonical worktree is absent and no alternate local checkout exists, the investigation cannot run policy/test perturbations.

Edge: Acquire or restore a local checkout of `kubescape/cel-admission-library`, then resume from H1 with the cached issue summary as the observation seed.

Status: killed.

Reasoning mode: Induction. Confidence: 95%.

## Graph State

| Node | Status | Trajectory | Evidence | Next Edge |
| --- | --- | --- | --- | --- |
| H0 | killed | divergent against | canonical worktree absent; GitHub/API unavailable; no cached checkout found | Restore checkout, then test C-0038 policy |

## Frontier Edges

| Edge | Pending Experiment | Predicted Classification | Confidence |
| --- | --- | --- | --- |
| E1 | Once a checkout exists, inspect `controls/C-0038/policy.yaml` and run the control's existing tests under the Docker test env. | Divergent if the expression really reads `hostPID` under a `has(object.spec.template.spec.hostIPC)` guard; convergent if tests already catch/fail. | 80% abduction from triage |

## Reasoning Mode Table

| Claim | Mode | Source | Confidence |
| --- | --- | --- | --- |
| The worktree is unavailable locally. | Induction | `sweep project-info`; filesystem search | 95% |
| GitHub issue/repo data cannot be fetched from this sandbox right now. | Induction | `gh issue view`; `git ls-remote` failures | 95% |
| The likely code change is `hostPID` to `hostIPC` in C-0038. | Abduction | cached triage attestation only, not yet verified against code | 70% |

## Pruning Log

| Node | Pruned Because | Evidence |
| --- | --- | --- |
| H0 | No perturbation surface exists in this environment. | Missing canonical worktree and blocked network access. |

## Provenance

Not run. Provenance requires repository history (`git blame`) and upstream issue/PR search. Both are blocked until a checkout and network/API access are available.

## Halt

Halted before Phase 2 under the rule: perturbation access is required. The graph is resumable from E1 once `/Users/junekim/.sweep/worktrees/kubescape__cel-admission-library` exists or another local checkout is provided.
