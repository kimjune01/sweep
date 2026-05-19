# yrosseel/lavaan#504 — `vcov(type="user")` and `vcov.def.joint` produce wrong dim-names

## H₀ (observation, deduction, 95%)

`vcov(fit, type = "user")` and `lavInspect(fit, "vcov.def.joint")` label rows/cols
with the bare `lhs` of each partable row (`x2`, `x3`, ...) instead of the
parameter labels used by `coef(fit, type = "user")` (`a`, `b`, `cp`, `x2~~x2`,
`x3~~x3`, `d`). The output dimensions and numerical values are correct; only
the names are wrong.

Repro: issue body. The reporter's own diff in `dimnames(vcov(fit, type="user"))`
makes this self-evident.

## H₁ (cause, deduction, 98%)

`R/lav_object_inspect.R:2724-2731` constructs names from `lavpartable$lhs[...]`
alone:

```r
if (add_labels) {
  if (joint) {
    lhs_names <- lavpartable$lhs[joint_idx]
  } else {
    lhs_names <- lavpartable$lhs[def_idx]
  }
  colnames(return_value) <- rownames(return_value) <- lhs_names
}
```

Every other coef/vcov labeller in lavaan delegates to
`lav_partable_labels(partable, type = "user")` (e.g. `lav_object_inspect_coef`
at `R/lav_object_inspect.R:3022`). That function builds `paste(lhs, op, rhs)`
as a default and overrides with `partable$label` where present, which is why
`coef(type="user")` shows `a`, `b`, `cp`, `x2~~x2`, …

The vcov_def path never got migrated to `lav_partable_labels`. Likely
historical: when only `lhs` was needed for definitions (`d := a*b` ⇒ `lhs="d"`),
the shortcut was fine; when `joint=TRUE` was added to splice the free-parameter
block on top, the shortcut produced rubbish for the free block.

## Perturbation

Replace the labelling block with a call to `lav_partable_labels(lavpartable,
type = "user")` and index by `joint_idx` / `def_idx`. This matches `coef`'s
naming exactly and fixes both call sites (`vcov(type="user")` via
`R/lav_object_methods.R:1273` and every `vcov.def*` / `vcov.def.joint*` branch
in `lav_object_inspect.R:555-590`).

## Trajectory

**Divergent (confirmed).** Tracing `lav_partable_labels` (R/lav_partable_labels.R:188)
with `type="user"` returns labels for all partable rows, using `partable$label`
where set (so `x2~x1` with `a*x1` becomes "a"). Subsetting by `joint_idx =
c(free_idx, def_idx)` yields exactly the names `coef(type="user")` would
produce, in the order vcov_def's `tmp_jac2 <- rbind(diag(...), tmp_jac)`
already uses. Numerical content untouched; correctness preserved by the matrix
algebra above the labelling block.

## Provenance

- Origin: `lav_object_inspect_vcov_def` predates the joint-vcov branch; the
  labelling code never grew with the function. No design intent in git history
  to keep raw `lhs` names.
- Related PRs: none open for "Names vcov" (per context pack).
- No upstream policy against contributor PRs.

## Frontier (open)

- `coef(fit, type="user")` returns 7 entries (including the fixed exogenous
  `x1~~x1`), while `vcov(fit, type="user")` returns a 6×6 matrix (free + def
  only). The reporter's headline complaint is the naming; whether the
  dimensions should also include fixed parameters is a separate design call
  outside the scope of this fix.

## Reproduction (cannot execute in this env)

`R` is not on PATH locally nor in `sweep-tester:latest`. Verification is
deductive: trace of `lav_partable_labels` ↔ `joint_idx` order. A reprex script
is committed at `prework/vcov-user-labels/reprex.R`; CI runs R and will
exercise the change.

## Diff (one file, 4-/3+ lines)

```
R/lav_object_inspect.R | 7 ++++---
1 file changed, 4 insertions(+), 3 deletions(-)
```
