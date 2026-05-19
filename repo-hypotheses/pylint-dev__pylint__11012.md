# pylint-dev/pylint #11012 — invalid-name FP for UPPER_CASE module-level function alias

**Issue:** `HTML = lxml_etree.HTML` at module level triggers C0103 (invalid-name) with
the default `[a-z_][a-z0-9_]{2,30}$` variable regex.

## H₀ — perturbation reproduces

Minimal repro (no lxml needed):

```python
def _helper(): ...
HELPER = _helper
```

`pylint --disable=all --enable=C0103` → emits
`Variable name "HELPER" doesn't conform to '[a-z_][a-z0-9_]{2,30}$' pattern`.

Trajectory: **divergent confirm**. Bug exists on `main` (HEAD `d523e3e89`).

## H₁ — control flow in `visit_assignname`

Source: `pylint/checkers/base/name_checker/checker.py:415-573`.

For module-level `Assign`, `safe_infer(value)` is consulted:

- If inferred is `FunctionDef`/`Lambda` → falls into `else` (line 514): `node_type = "variable"`,
  then `_check_name("variable", ...)`.
- `_meets_exception_for_non_consts` (line 567) is the escape hatch — it returns True (skip emit)
  if inferred is non-Const **and** name matches the `variable` regex.
- Name `HELPER` matches neither variable regex (snake_case) nor escape → message fires.

## H₂ — documented policy is symmetric, code is asymmetric

PR #10212 (`c66868215`) reshaped this branch and added `doc/whatsnew/fragments/3585.breaking`:

> Values other than literals (lists, sets, objects) can pass against **either the constant or
> variable regexes** (e.g. "LOGGER" or "logger" but not "LoGgEr").

The shipped `_meets_exception_for_non_consts` only checks the **variable** regex. For
function aliases at module level (a non-literal value), the doc promises `LOGGER` should pass
— but the code only honors `logger`. The asymmetry is the bug.

Trajectory: **divergent**. Doc-vs-code mismatch is the kill condition for "this is intended".

## Fix

Extend the exception in `_meets_exception_for_non_consts` to also accept names matching the
const regex, matching the documented symmetric policy.

```python
def _meets_exception_for_non_consts(self, inferred_assign_type, name):
    if isinstance(inferred_assign_type, nodes.Const):
        return False
    return (
        self._name_regexps["variable"].match(name) is not None
        or self._name_regexps["const"].match(name) is not None
    )
```

This already-called helper guards both the const branch (line 509) and the variable branch
(line 529), so the symmetric escape lands in both places.

Literal values (`AAA = 24` → `nodes.Const`) still require the const regex, preserving the
existing test `aaa = 42 # [invalid-name]`.

## Regression surface

Existing functional tests:

- `tests/functional/i/invalid/invalid_name.py` — `aaa = 42` etc. all assign literals
  (`nodes.Const`); the new branch returns False unchanged.
- `tests/functional/n/name/name_styles.py` — verified locally, no expected message changes.

## Provenance

- `_meets_exception_for_non_consts` introduced in PR #10212 (Jacob Walls, 2025-03-02).
- Doc fragment `3585.breaking` already promises symmetric behavior; this PR brings the code
  in line with the docs.
- No prior PRs by kimjune01 on this repo; no open PRs match `C0103 Variable`.

## Reasoning modes

| Claim | Mode | Confidence |
|-------|------|------------|
| Bug reproduces with `HELPER = _helper` | induction (ran it) | 99% |
| Branch taken is `else` at line 514 | deduction (read code) | 95% |
| Doc promises both regexes accepted | deduction (read 3585.breaking) | 99% |
| Symmetric fix preserves existing tests | abduction + spot check | 85% |
