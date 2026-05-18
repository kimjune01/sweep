# Automattic/harper#3405 Hypothesis Graph

Investigation started: 2026-05-18T16:39:09Z

## Task

Investigate `Automattic/harper#3405`.

## Environment Routing

`sweep project-info Automattic/harper` returned:

```json
{
  "repo": "Automattic/harper",
  "worktree": "/Users/junekim/.sweep/worktrees/Automattic__harper",
  "worktree_exists": false,
  "test_env": "docker:sweep-tester:latest",
  "test_cmd": null,
  "test_setup_cmd": null,
  "evicted": false,
  "notes": [
    "test_env defaulted to sweep-tester image"
  ]
}
```

QA parity target, if a worktree becomes available: run tests in `docker:sweep-tester:latest` with the worktree mounted at `/work`.

## H0 - Perturbation Surface Is Available

- Hypothesis: The target issue and repository can be inspected and perturbed locally.
- Null: The issue/repository cannot be accessed from this runtime, so the hypothesis graph cannot progress beyond observation.
- Perturbation:
  - `gh issue view 3405 --repo Automattic/harper --json number,title,body,labels,state,url,author`
  - `git clone https://github.com/Automattic/harper.git /private/tmp/harper`
  - Search writable local roots for Harper worktrees and issue caches.
  - Browser search/open for public repository and issue metadata.
- Result:
  - `gh issue view` failed with `error connecting to api.github.com`.
  - `git clone` failed with `ssh: Could not resolve hostname github.com: -65563`.
  - Canonical worktree path does not exist and is outside this sandbox's writable roots.
  - No Harper checkout or issue #3405 cache exists under `/Users/junekim/Documents/sweep`, `/private/tmp`, or the inspected temp root.
  - Public web search confirms the repository exists, but direct issue #3405 content was not retrievable in this session.
- Trajectory shape: Divergent against H0.
- Status: killed.
- Kill condition: No local perturbation surface and no issue payload.
- Edge: Restore perturbation access, then restart Phase 1. Minimal sufficient inputs are either a local Harper checkout plus issue #3405 text, or network access allowing `gh issue view` and `git clone`.

### Provenance

- `sweep project-info` established the canonical worktree and test environment before any build/test command was attempted.
- Existing checkpoint `repo-hypotheses/Automattic-harper.md` concerns PR #3336 / issue #3276, not issue #3405.
- Local search for `3405`, `Automattic/harper`, and `Automattic__harper` found no cached issue payload for this task.

## Graph State

| Node | Hypothesis | Mode | Perturbation | Trajectory | Status | Edge |
|------|------------|------|--------------|------------|--------|------|
| H0 | Target issue/repo perturbation surface is available | Induction | `project-info`, `gh issue view`, `git clone`, local cache search, browser lookup | Divergent against | killed | Restore worktree/issue access, restart observation |

## Frontier Edges

| Edge | Next Experiment | Predicted Classification | Confidence |
|------|-----------------|--------------------------|------------|
| E0 | Provide or materialize a writable Harper checkout and issue #3405 body; run the issue's most direct reproduction | Divergent or convergent depending on reproduction | 90% that access unblocks; 0% diagnosis confidence until reproduction runs |

## Reasoning Mode Table

| Claim | Mode | Confidence |
|-------|------|------------|
| QA should be mirrored with `docker:sweep-tester:latest` | Deduction from `project-info` | 95% |
| This runtime lacks local Harper perturbation access | Induction from filesystem and clone/search commands | 95% |
| Issue #3405 cannot be diagnosed yet | Deduction from the perturbation-access rule plus missing issue/worktree | 99% |

## Pruning Log

- Killed H0 because both required inputs are absent: issue text and a perturbable worktree. Continuing would be speculative and would violate the perturbation-access rule.

## Current Halt

`human-gated`: the investigation cannot proceed without a perturbation surface. Resume by supplying a local checkout path under a writable root, pasting the issue #3405 body, or enabling access for `gh`/`git` to fetch them.
