# Hypothesis Graph: Automattic/wordpress-activitypub#3306

Investigation started: 2026-05-18

## Access And Routing

- Target: `Automattic/wordpress-activitypub#3306`
- Canonical project-info:
  - `worktree`: `/Users/junekim/.sweep/worktrees/Automattic__wordpress-activitypub`
  - `worktree_exists`: `false`
  - `test_env`: `docker:sweep-tester:latest`
  - `test_cmd`: `null`
  - `test_setup_cmd`: `null`
- Local sandbox writable roots do not include `/Users/junekim/.sweep/worktrees`, so the canonical worktree cannot be created from this session.
- Fallback in-workspace checkout attempted at `worktrees/Automattic__wordpress-activitypub`.
- Shell network is unavailable: `git clone`, `gh issue view`, and `curl` all fail before HTTP with DNS/connection errors.
- Public web search exposed repo-level metadata but not the body of issue #3306.

## Graph State

| Node | Status | Trajectory | Mode | Confidence | Summary |
| --- | --- | --- | --- | --- | --- |
| H0 | killed | divergent | induction | 95% | Perturbation access is required; the target checkout and issue body are unavailable in this environment. |

## Nodes

### H0: This environment can perturb Automattic/wordpress-activitypub#3306 locally

- Hypothesis: A local checkout and issue body can be obtained, allowing observation and fan-out.
- Null: The target system cannot be poked from this session, so no code-level investigation can proceed.
- Perturbation:
  - `sweep project-info Automattic/wordpress-activitypub`
  - `gh issue view 3306 --repo Automattic/wordpress-activitypub --json number,title,state,body,comments,url,labels,author`
  - `git clone --quiet https://github.com/Automattic/wordpress-activitypub.git /Users/junekim/.sweep/worktrees/Automattic__wordpress-activitypub`
  - `git clone --quiet https://github.com/Automattic/wordpress-activitypub.git worktrees/Automattic__wordpress-activitypub`
  - `curl -I --max-time 10` against GitHub raw, SourceForge mirror, and ecosyste.ms issue API endpoints.
- Result:
  - `project-info` returned a canonical worktree outside writable roots, with `worktree_exists=false`.
  - `gh issue view` failed: `error connecting to api.github.com`.
  - Canonical clone failed: `Operation not permitted` creating `/Users/junekim/.sweep/worktrees/Automattic__wordpress-activitypub`.
  - In-workspace clone failed: `ssh: Could not resolve hostname github.com: -65563`.
  - `curl` probes failed with `Could not resolve host`.
  - Web search found repo-level pages and metadata, but not issue #3306 content.
- Trajectory shape: Divergent against the hypothesis. Every perturbation that would expose the system failed at filesystem permission or DNS/network access.
- Kill condition: No readable checkout and no issue body means the system cannot be perturbed.
- Edge: Resume from H1 once either a local checkout is present under a writable path or the issue body/code snapshot is supplied.
- Provenance:
  - Origin commit: unavailable; no checkout.
  - Upstream issues/PRs: unavailable for issue #3306; search only surfaced repo-level metadata and unrelated indexed pages.
  - Risk assessment: any diagnosis without the issue body or code perturbation would be speculative and violates the investigation rule requiring perturbation access.

## Frontier Edges

| Edge | Pending perturbation | Predicted classification | Confidence |
| --- | --- | --- | --- |
| E1 | Provide or create a readable checkout at `/Users/junekim/Documents/sweep/worktrees/Automattic__wordpress-activitypub`, then read issue #3306 and run the most direct reproduction. | Divergent or convergent depending on the issue's reported behavior. | 90% |
| E2 | If shell DNS is restored, rerun `gh issue view 3306 --repo Automattic/wordpress-activitypub` and clone/fetch the repo. | Divergent toward actionable investigation if network succeeds. | 90% |
| E3 | If only a code snapshot is available, use it with the issue body as the observation surface and downgrade provenance confidence by 10% because live issue/PR search remains unavailable. | Convergent partial access. | 80% |

## Reasoning Mode Table

| Claim | Mode | Confidence | Evidence |
| --- | --- | --- | --- |
| The canonical worktree is absent and outside writable roots for this session. | induction | 95% | `sweep project-info` plus failed canonical clone. |
| Shell network access is blocked at DNS resolution. | induction | 95% | `git clone` and `curl` failures before HTTP. |
| Code-level hypothesis fan-out would be speculative right now. | deduction | 97% | No issue body, no checkout, no runnable perturbation surface. |

## Pruning Log

- H0 killed because perturbation access is not available. The next node must start from restored access, not from inferred issue content.

## Blind-Blind Pushout

Not run. The evidence pack lacks the minimum inputs for a blind pushout: no issue body and no code snapshot. Running parallel abductions on only a repo name and issue number would manufacture hypotheses without evidence.

## Halt

Halted before Phase 2 by the rule: perturbation access is required. Resume when the issue body and a readable checkout are available.
