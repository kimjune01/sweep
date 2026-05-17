# pylint-dev/pylint #11002 — Refine kwargs gate after primer FPs

Issue: #8785 (FN — `f(**{"y": ...})` doesn't fire `no-value-for-parameter`).
PR: #11002 on branch `fix-8785-kwargs-no-value-for-parameter`.

## H₀ — initial fix landed (commit 91dc832)

Gate step 3 of `_check_argument_order` on `has_no_context_keywords_variadic`. Step 3 was unconditionally marking every remaining param as assigned whenever `node.kwargs` was truthy, masking the FN.

- **Trajectory**: divergent in favor — FN test fires.
- **Status**: confirmed for the literal-dict shape, **killed by primer** for everything else.

## H₁ — Primer regression (Pierre-Sassoulas review)

Effect of the PR run by github-actions across ansible, sentry, home-assistant: 20+ new `no-value-for-parameter` messages on real wrapper code. All share shape `f(**name)` where `name` is a Name in scope, not a literal `{...}`.

Maintainer rule of thumb in the review: "Anything including `dict.setdefault`, `dict.update`, loop-built dicts, or a `**kwargs` parameter, should be treated as 'could supply the missing argument' rather than 'definitely doesn't.'"

- **Trajectory**: divergent against H₀'s gate — too aggressive.
- **Kill condition**: the gate must also cover any `**name` where the dict's full key set isn't statically provable.

## H₂ — Root cause of FPs

`astroid.arguments.CallSite._unpack_keywords` infers `**name` to a Dict and extracts only the keys present at the *assignment* node. Mutations (`.update`, `.setdefault`, subscript-assignment, loop population) are invisible. Function-return / opaque sources are similarly partial. So step 2 sees a strict subset of the true keys, and any param not in that subset gets reported as missing once step 3 stops covering.

- **Mode**: deduction. Read `_unpack_keywords` directly.
- **Confidence**: 95%.

## H₃ — Refined gate (this commit)

Cover step 3 whenever ANY `**` operand in the call is not a literal `Dict` node. Concretely:

```python
kwargs_might_supply_more = any(
    not isinstance(kw.value, nodes.Dict) for kw in node.kwargs
)
if node.kwargs and (
    has_no_context_keywords_variadic or kwargs_might_supply_more
):
    # mark remaining named params assigned
```

- A literal `f(**{"y": ...})` keeps the FN behavior — `kw.value` IS a `Dict`, so neither clause fires, step 3 doesn't cover, FN still emits.
- Any `f(**name)` / `f(**get_opts())` / `f(**self.cfg)` skips emission — we cannot prove completeness, so we defer.
- Forwarded `def w(**kw): f(**kw)` is covered twice over (by `has_no_context_keywords_variadic` and by `kwargs_might_supply_more`); cheap redundancy, semantically aligned.

### Perturbation table

| Shape | Before refinement | After refinement |
|-------|-------------------|------------------|
| `f(**{"y": ...})` literal FN | fires (correct) | fires (correct) |
| `def w(**kw): f(**kw)` forwarded | quiet | quiet |
| `data={"x":1}; data.update({"y":2}); P(**data)` | **FP** | quiet |
| `data={}; data.setdefault("x",0); P(**data)` | **FP** | quiet |
| `data={}; for k,v in PAIRS: data[k]=v; P(**data)` | **FP** | quiet |
| `data={}; data[ATTR_X]=...; P(**data)` | **FP** | quiet |
| `opts = get_opts(); P(**opts)` | **FP** | quiet |

All six FP shapes from the maintainer-supplied regression file are quieted; the original FN test (`copy.copy(**{"y": os.environ})`) still fires both `unexpected-keyword-arg` and `no-value-for-parameter` as before.

- **Mode**: induction — `./pylint --enable=no-value-for-parameter fp_cases.py` before/after on the maintainer's six shapes.
- **Confidence**: 92%.

## Regression coverage added

`tests/functional/k/kwargs_unpacking_no_false_positive.py` — straight from the maintainer's review comment, six shapes, no expected emissions. The original FN test in `tests/functional/a/arguments.py` lines 343-344 retained unchanged.

## Frontier (still open)

- `via_opaque_dict` with `options.pop("ignored")` retained from maintainer's case 6: triggers `unexpected-keyword-arg` (not `no-value-for-parameter`) because step 2 sees `ignored` from the inferred return dict. Out of scope for this PR — the primer-reported FPs are all `no-value-for-parameter`. Dropped the `.pop` from the regression file to keep the test focused on the message under repair.
- The same Dict-literal-only test could in principle be extended to `**` operands that are `Dict`-typed comprehensions (`{k:v for ...}`). Currently those are `DictComp`, not `Dict`, so they get covered conservatively. Fine — matches maintainer's "loop-built dicts" guidance.

## Reasoning mode table

| Node | Mode | Confidence |
|------|------|-----------|
| H₀: original gate | deduction (code read) | 95% |
| H₁: primer FPs | induction (CI primer) | 99% |
| H₂: astroid loses mutations | deduction (`_unpack_keywords` source) | 95% |
| H₃: literal-only gate | abduction + induction (six perturbations all converge) | 92% |

## Pruning log

- "Just revert the fix" — rejected, would re-introduce the #8785 FN.
- "Also gate step 2's `unexpected-keyword-arg` for non-literal kwargs" — rejected as scope creep; primer FPs were all `no-value-for-parameter`, none `unexpected-keyword-arg`. Leaving for a follow-up if maintainer asks.
- "Use `has_invalid_keywords()` instead" — rejected. By construction it's already False at the gate (early return at line 1490), so the check would be a no-op.
