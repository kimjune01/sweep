# EnzymeAD/Enzyme-JAX#2487 Hypothesis Graph

Investigation: 2026-05-18 (blocked on access). Resumed: 2026-05-19 (access restored).

## Target

- Repo: `EnzymeAD/Enzyme-JAX`
- Issue: `#2487` — "Improve raising for compare with non-step size"
- Body: "Fix the case in https://github.com/EnzymeAD/Enzyme-JAX/pull/2486/changes to raise, rather than just get side-stepped"
- Author: wsmoses (project lead)
- Worktree: `/Users/junekim/.sweep/worktrees/EnzymeAD__Enzyme-JAX`
- Test env: `docker:sweep-tester:latest` (no `enzymexlamlir-opt` / `bazel` in image — local lit run not possible)

## H0 — Access (resolved)

Stale 2026-05-18 entry said access blocked. Reproduced on 2026-05-19: `gh` works, clone into the canonical worktree succeeds. Stale finding **invalidated**.

## H1 — PR #2486 added a guard that *blocks* the buggy pattern; #2487 asks for a real raising

- **Hypothesis**: PR #2486 added a check in `WhileToForHelper::considerStep` that bails out when the cmp operand is `(iv + invariant_offset)` and the actual induction step lives in the after region. The test it shipped (`nonstepadd.mlir`) has a `TODO we should support raising this loop` and asserts the loop is preserved. Issue #2487 asks: do the raising instead.
- **Perturbation**: read `gh pr diff 2486`, `git blame` on `considerStep`, read `CanonicalizeFor.cpp:1217-1273`.
- **Result**: confirmed. The added guard at `CanonicalizeFor.cpp:1231-1246` rejects when `afterYield.getOperand(ba2.getArgNumber())` is not a `BlockArgument` — exactly the case where the after region computes the real induction step via an `addi`.
- **Trajectory**: divergent for. **Confirmed.**
- **Mode**: deduction (read the code, traced consequences). Confidence 95%.

## H2 — Fix shape: detect the after-region addi and shift the bound

- **Hypothesis**: when the new guard would reject, recognize the pattern `afterYield[ba2.argNum] = addi(after_arg, real_step)` with `condOp.args[after_arg.argNum] == ba2`. Treat `add->getOperand(1-j)` (the other operand of the *before* add) as a loop-invariant offset and subtract it from the upper bound (forward) / lower bound (reverse).
- **Equivalence**: `j + offset < bound` ⇔ `j < bound - offset` (assuming no wrap).
- **Perturbation**: implemented in `considerStep`; threaded `cmpOffset` through `prepareFor`. Reviewed by codex (GPT-5.5) twice.
- **Trajectory**: converged after addressing codex's first-round findings.

### Codex round 1 findings → fixes

| Severity | Concern | Fix |
|---|---|---|
| High | Loop-invariance check was ad hoc (only checked defining op, not block-arg ownership). | Replaced with `dominateWhile(offset, loop)` and `dominateWhile(realStep, loop)`. |
| High | `cmpi ne`'s divisibility / reachability logic uses unshifted `cmpStart`/`cmpEnd`. | Reject `cmpOffset` for the `ne` predicate. |
| Medium | `ExtSIOp` is stripped from cmp operand in `computeLegality`, so `offset` and `ub` could be different widths. | Reject if `cmpIOp->getOperand(compareIndex).getType() != offset.getType()`. |
| Low (kept) | Wrap/overflow: `iv + offset < bound` ≡ `iv < bound - offset` only without wrap. | Match existing convention — no other transform in this file checks `nsw`/`nuw` (the existing `lb_addStep` path has the same risk). Document as a known limitation matching existing behavior. |

### Codex round 2

All three high/medium fixes accepted. Only remaining note: wrap concern (kept as a known limitation, see above).

## Graph State

| Node | Status | Trajectory | Mode | Confidence |
|---|---|---|---|---:|
| H0 | retired | — | induction | 100% (access restored) |
| H1 | confirmed | divergent | deduction | 95% |
| H2 | confirmed | converged after 2 codex rounds | abduction → deduction | 85% |

## Frontier Edges

| Edge | Status | Predicted Classification | Next Perturbation |
|---|---|---|---|
| F1 (wrap safety) | open, accepted as existing-behavior parity | divergent if maintainer wants stricter | If reviewer flags, add overflow-flag check on the *before* add. |
| F2 (CI on real shape) | open | divergent | CI runs lit on `nonstepadd.mlir`; test uses lenient `CHECK:`/`CHECK-NOT:` so output-shape drift won't false-fail. |

## Reasoning Mode Table

| Claim | Mode | Provenance | Confidence |
|---|---|---|---:|
| PR #2486 blocks raising of `iv + offset` compare. | deduction | `gh pr diff 2486` + code read | 95% |
| The transformation is `ub -= offset` for forward, `lb -= offset` for reverse. | deduction | algebra + `checkPredicate` semantics | 95% |
| The new test still passes if exact var numbering changes. | deduction | rewrote test with `CHECK:`/`CHECK-NOT:` (no `CHECK-NEXT`) | 90% |
| Wrap is a known concern not enforced by surrounding code. | deduction | `grep -n "overflow\|nsw\|nuw"` in `CanonicalizeFor.cpp` → no hits | 95% |

## Pruning Log

| Node | Pruned Why |
|---|---|
| H0 (stale) | Network access restored; the original H0 was an artifact of an earlier sandbox state. |

## Provenance

- Guard origin commit: PR #2486 ("Block incorrect scf for raising"), merged. Same author (wsmoses) authored the follow-up issue (#2487). This is intentional handoff: block-now-fix-later, not a missed mechanism.
- No adjacent open PR addresses #2487 (`gh pr list --search 'Improve raising'` empty in pre-fetched pack).
- Operator has no prior PRs on this repo.
