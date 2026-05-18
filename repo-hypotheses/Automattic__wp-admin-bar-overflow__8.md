# Hypothesis Graph: Automattic/wp-admin-bar-overflow#8

**Issue**: Plugins dropdown trigger should close on second click
**Date**: 2026-05-18
**Project routing**:

```json
{
  "repo": "Automattic/wp-admin-bar-overflow",
  "worktree": "/Users/junekim/.sweep/worktrees/Automattic__wp-admin-bar-overflow",
  "worktree_exists": false,
  "test_env": "docker:sweep-tester:latest",
  "test_cmd": null,
  "test_setup_cmd": null
}
```

**Access state**: Blocked before executable perturbation. The canonical worktree does not exist locally, `gh issue view` cannot reach `api.github.com`, and `git ls-remote https://github.com/Automattic/wp-admin-bar-overflow.git HEAD` fails DNS resolution for `github.com`. Browser search can see public issue/repo metadata incompletely, but shell tools cannot clone, fetch, run tests, or patch the target system.

## Evidence Pack

- Triage attestation: `~/.sweep/attestations/triage/Automattic__wp-admin-bar-overflow__8.md`
- Issue title: "Plugins dropdown trigger should close on second click"
- Triage summary: bug-labeled, recent on 2026-05-15, structured browser repro, explicit expected/actual, issue body sketches a test with a toggle and `aria-expanded` assertion.
- Local perturbation surface expected, but absent: JavaScript click handler and browser tests in `/Users/junekim/.sweep/worktrees/Automattic__wp-admin-bar-overflow`.

## Blind-Blind Pushout

### Hypothesis A: Primary

Root cause likely sits in the dropdown trigger state machine: the click handler opens the Plugins overflow dropdown on click but does not treat a click on the already-open trigger as a close request. The candidate fix shape is to derive the next state from current open state, then update both visual state and `aria-expanded`.

Proposed perturbation once worktree exists: run or add the browser/unit test sketched by the issue: click the Plugins trigger once and assert open/`aria-expanded="true"`; click the same trigger again and assert closed/`aria-expanded="false"`.

### Hypothesis B: Pushout

Independent explorer converged on the same state-machine hypothesis: close behavior is probably delegated to outside-click/focus-loss, so a second click on the same trigger is not classified as outside and the handler re-applies or preserves open state. It also flags sibling-dropdown handling as a possible adjacent edge: close sibling dropdowns when opening another trigger, while closing instead of reopening the same trigger.

Confirming perturbation: instrument the click handler and log `aria-expanded` plus open class before mutation. If the second click sees open state and still calls the open branch or leaves the open class intact, H1 is supported.

Refuting perturbation: force a minimal toggle and observe whether the dropdown remains visible even after class and ARIA state are false. If so, the cause is likely CSS hover/focus behavior, duplicated event handlers, or another listener reopening the menu.

### Where A and B Diverge

No substantive divergence in root cause or fix shape. B adds a specific alternative edge: if minimal toggle updates ARIA/classes but the menu stays visible, inspect CSS hover/focus and duplicate listeners. This becomes H2 if H1 is killed.

## Nodes

### H0: Baseline Repro Exists But Cannot Be Run Locally

- **Hypothesis**: The issue describes a deterministic browser repro: first click opens the Plugins dropdown; second click should close it but does not.
- **Null**: The repro is stale, environment-specific, or already fixed upstream.
- **Perturbation**: Attempt to establish baseline by resolving worktree and issue context.
- **Result**: `sweep project-info` reports `worktree_exists: false`; `gh issue view` and `git ls-remote` fail because shell network access cannot resolve/reach GitHub.
- **Trajectory shape**: Divergent against local investigation readiness, not against the product behavior.
- **Kill condition**: A local worktree becomes available and the browser repro cannot be reproduced on default branch.
- **Edge**: Acquire or restore `/Users/junekim/.sweep/worktrees/Automattic__wp-admin-bar-overflow`, then run the issue's click/ARIA test.
- **Reasoning mode**: Induction for access result (95%); abduction for product behavior from issue/triage (70%).
- **Status**: Partial, blocked by missing perturbation surface.

### H1: Same-Trigger Click Does Not Toggle Closed

- **Hypothesis**: The Plugins dropdown trigger has an asymmetric click handler: click opens, but a second click on the same already-open trigger preserves/reopens instead of closing.
- **Null**: The handler toggles correctly; the visible bug comes from CSS hover/focus state, duplicated event listeners, event propagation ordering, or stale test assumptions.
- **Perturbation**: Add/run a browser/unit test: click trigger once, assert dropdown open and `aria-expanded="true"`; click trigger again, assert dropdown closed and `aria-expanded="false"`.
- **Predicted trajectory**: Divergent support if second click leaves `aria-expanded` true or open class present. Divergent refutation if ARIA/classes toggle but visibility still wrong.
- **Kill condition**: The second click toggles state correctly in code/tests, or a minimal toggle patch does not change visible behavior.
- **Edge**: If confirmed, implement minimal toggle in existing click handler and update the issue-sketched test. If killed, follow H2.
- **Provenance**: Pending; requires local git history and issue/PR search once worktree/network is available.
- **Reasoning mode**: Abduction from issue evidence plus blind pushout convergence (80%).
- **Status**: Open.

### H2: CSS/Focus/Listener Reopens Or Displays Menu After State Closes

- **Hypothesis**: The JavaScript state may close correctly, but CSS `:hover`/`:focus`, event bubbling, or a second listener immediately reopens/keeps displaying the dropdown.
- **Null**: Visibility follows JS state exactly; the bug is entirely the missing toggle branch in H1.
- **Perturbation**: After forcing/logging close state, inspect computed styles and listener order after second click; assert menu hidden when `aria-expanded="false"` and open class absent.
- **Predicted trajectory**: Divergent support if visual menu remains displayed despite closed ARIA/classes.
- **Kill condition**: Visual state closes when JS state closes.
- **Edge**: If confirmed, patch event ordering or CSS/focus behavior using existing project convention.
- **Provenance**: Pending.
- **Reasoning mode**: Abduction from pushout alternative (65%).
- **Status**: Frontier.

## Graph State Table

| Node | Status | Shape | Summary |
| --- | --- | --- | --- |
| H0 | partial | divergent-access | No local worktree or shell network; baseline repro cannot be run. |
| H1 | open | predicted divergent | Same-trigger click likely fails to toggle closed. |
| H2 | frontier | predicted divergent if H1 killed | CSS/focus/listener interaction may keep menu visible after state closes. |

## Frontier Edges

| Edge | Next perturbation | Predicted classification | Priority |
| --- | --- | --- | --- |
| H0 -> H1 | Restore/clone worktree, run issue repro/test for double-click toggle and `aria-expanded`. | Divergent support for H1 if second click leaves menu open. | P0 |
| H1 -> fix | Implement minimal toggle branch in existing handler, add/adjust test. | Convergent if test fails on base and passes with fix. | P1 |
| H1 killed -> H2 | Log listener order/computed style after second click. | Divergent support for CSS/focus/listener root cause if ARIA closes but UI remains open. | P2 |

## Reasoning Mode Table

| Claim | Mode | Provenance | Confidence |
| --- | --- | --- | --- |
| Local worktree is absent. | Induction | `sweep project-info Automattic/wp-admin-bar-overflow` | 95% |
| Shell cannot reach GitHub currently. | Induction | `gh issue view`; `git ls-remote` DNS/API failures | 95% |
| Issue has structured repro and likely test sketch. | Deduction over triage artifact | Local triage attestation | 90% |
| H1 is likely root cause. | Abduction | Primary + blind pushout convergence from issue evidence | 80% |
| H2 is an alternative if H1 patch fails. | Abduction | Pushout refutation path | 65% |

## Pruning Log

- No product hypotheses pruned yet. The investigation lacks perturbation access, so pruning would be overclaiming.

## Blocker

Perturbation access is required and currently missing. Resume by creating/restoring the canonical worktree:

```bash
sweep project-info Automattic/wp-admin-bar-overflow --field worktree
```

Then, with network/worktree restored, rerun Phase 1 baseline before any patch:

```bash
sweep project-info Automattic/wp-admin-bar-overflow
```

If `test_env` remains `docker:sweep-tester:latest`, mirror QA with:

```bash
docker run --rm -v $(sweep project-info Automattic/wp-admin-bar-overflow --field worktree):/work -w /work sweep-tester:latest <test-command>
```

