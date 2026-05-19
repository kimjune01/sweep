# pylint-dev/pylint#10994 — False positives when `type` builtin is overwritten

## H₀ — Reproduction in pylint main + astroid 4.2.0b3

- **Perturbation**: run `pylint --errors-only /tmp/a.py` with the reporter's snippet inside `sweep-tester` container, against current `pylint-dev/pylint@main` editable install pulling its pinned `astroid==4.2.0b3`.
- **Result**: `E1101: Class 'float' has no 'split' member (no-member)` (rc=2). Identical to the reporter.
- **Shape**: divergent — bug exists in latest dependencies. Mode: induction (95%).

## H₁ — Root cause is astroid's `_builtin_filter_predicate`, not pylint

Reporter MCharming98 named the file. Verified directly.

- **File**: `astroid/brain/brain_builtin_inference.py` (astroid 4.2.0b3), function `_builtin_filter_predicate`, line ~181:
  ```py
  if isinstance(node.func, nodes.Name):
      return node.func.name == builtin_name
  ```
- The predicate gates `register_builtin_transform(... "type")` (line 1055), which installs `infer_type` as an inference tip on any `Call` node whose callee Name equals `"type"`. It never resolves the Name through `lookup()` to confirm it's actually the builtin.
- Because the predicate fires on the local `type` parameter, `infer_type(convert_type(12.34, str))` returns `float` (i.e. `type(12.34)`), pylint then concludes the call's value is the `float` class, hence no-member on `.split`.
- **Cross-check**: `brain_type.py` (subscript path) does perform a proper inference check (per reporter); only the call-path predicate is broken.
- **Shape**: divergent confirm. Mode: deduction (98%) — code path traced end-to-end.

### Provenance

- Predicate has lived in `brain_builtin_inference.py` since the file's creation (pre-2014 in astroid history). It's the registration shape for *all* builtin transforms, not specific to `type`. A literal `lookup()`-based fix on `type` alone is the minimal change; generalising to every builtin transform risks regressions on other inference tips that downstream code relies on.
- No open astroid PR addresses `_builtin_filter_predicate`-and-shadowing as of pack time.
- pylint side has issue #11002 (different bug, no-value-for-parameter false negative).

## H₂ — Fix lives in astroid, not pylint

- **Perturbation**: search the pylint worktree for any local override of builtin inference for `type`. None exists; pylint consumes astroid's inferred values via `safe_infer`. The `no-member` checker (`pylint/checkers/typecheck.py`) reasons over astroid's already-inferred class object — by the time pylint sees the call, the transform has already collapsed it to `float`.
- **Shape**: divergent — there is no pylint-side surface to patch without re-implementing astroid's inference. Mode: deduction (95%).
- **Edge**: this issue is mis-filed against pylint. The fix is a one-liner in `astroid/brain/brain_builtin_inference.py` (replace name-only predicate with `lookup()`-based check) and an astroid regression test.

## Frontier / next action

The repository under investigation cannot host the fix. Two operator options:

1. **File at astroid.** Open a fresh issue at `pylint-dev/astroid` describing the predicate bug + minimal repro, link back to pylint#10994. Maintainer there can patch `_builtin_filter_predicate` to consult `lookup()` for the local scope. This is the load-bearing action.
2. **Comment on pylint#10994.** Note that the root cause is the astroid predicate and link to the astroid issue once filed. No pylint code change.

**Halt — human-gated.** The investigation has a confirmed upstream diagnosis but no pylint-side fix surface. Routing to astroid (different repo) is an operator decision, not something to ship as a pylint PR.

## Graph state

| Node | Status | Mode | Confidence |
|---|---|---|---|
| H₀ reproduction | confirmed | induction | 95% |
| H₁ predicate ignores shadowing | confirmed | deduction | 98% |
| H₂ fix is upstream-only | confirmed | deduction | 95% |
