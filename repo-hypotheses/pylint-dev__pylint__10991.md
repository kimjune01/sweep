# pylint-dev/pylint#10991 — Hypothesis Graph

**Issue:** `E1123: Unexpected keyword argument 'value'` is raised for a `@dataclass` whose grandparent owns the field, when the intermediate class uses PEP 695 `TypeVarTuple` syntax (`Middle[T, *Shape]`) and the grandchild forwards the unpacking in its base spec (`Upper[T, *Shape](Middle[T, *Shape])`).

**Versions reproduced on:** pylint 4.1.0-dev0, astroid 4.2.0b3, Python 3.12.11.

**Root cause locality:** astroid (`pylint-dev/astroid`), not pylint. Fix belongs in `pylint-dev/astroid`.

---

## H0 — Reproduction (Induction, 95%)

Perturbation: run pylint on the issue's MWE.

```
pylint --disable=all --enable=E1123 repro.py
→ repro.py:15:6: E1123: Unexpected keyword argument 'value' in constructor call
```

Trajectory: **divergent** against the expected behavior. Bug is real and triggers on every run.

## H1 — Maintainer's load-bearing comment (Abduction, 70%)

`MCharming98` proposed: `_infer_sequence_helper` in `astroid/nodes/node_classes.py` fails on `Starred(TypeVarTuple)` because the inferred starred value has no `.elts`. The InferenceError bubbles up through Tuple inference, then through Subscript inference for the base spec, then `ClassDef.mro()` silently drops the inheriting base — so the inherited `value` field disappears from the dataclass field list.

Perturbation: trace the inference path on the MWE.

## H2 — Trace confirms the chain (Deduction, 95%)

```python
upper = mod.body[-1]          # class Upper[T, *Shape](Middle[T, *Shape])
sub   = upper.bases[0]        # Subscript: Middle[T, *Shape]
list(sub.infer())             # → InferenceError("Inference failed for <Tuple.tuple ...>")
upper.mro()                   # → ['Upper']  (Middle and Base dropped)
```

Trajectory: **divergent for**. The maintainer's diagnosis is right at the symptom level.

## H3 — But the failure is one hop deeper than the comment says (Deduction, 95%)

The comment says "Starred contains a TypeVarTuple, has no `.elts`." Actually `util.safe_infer(elt.value, context)` on `Name('Shape')` does **not** return a TypeVarTuple — it returns `Const(None)`. The cause: `protocols.generic_type_assigned_stmts` (protocols.py:943) is a hack that yields `Const(None)` for every `TypeVar | TypeVarTuple | ParamSpec` AssignName:

```python
def generic_type_assigned_stmts(...):
    """Hack. Return any Node so inference doesn't fail
    when evaluating __class_getitem__. Revert if it's causing issues."""
    yield nodes.Const(None)
```

So checking `isinstance(starred, TypeVarTuple)` after `safe_infer` would never match. The narrow detection has to happen at the **Name lookup** layer, before safe_infer collapses to Const(None).

Provenance: this hack predates PEP 695 syntax (it was written for `__class_getitem__` runtime support); when the slice tuple started containing Starred nodes, the hack's downstream consumers stopped fitting.

## H4 — Patch: detect at the lookup layer (Induction, 95%)

In `astroid/nodes/node_classes.py`, before invoking `safe_infer` on the starred value, check whether the unpacked name binds to a `TypeVarTuple` AssignName. If so, preserve the original `Starred` element in the inferred sequence instead of expanding or raising:

```python
def _starred_unpacks_typevartuple(starred: "Starred") -> bool:
    value = starred.value
    if not isinstance(value, Name):
        return False
    try:
        _, assignments = value.lookup(value.name)
    except Exception:
        return False
    return any(
        isinstance(getattr(node, "parent", None), TypeVarTuple)
        for node in assignments
    )

# inside _infer_sequence_helper, at the Starred branch:
if isinstance(elt, Starred):
    if _starred_unpacks_typevartuple(elt):
        values.append(elt)
        continue
    starred = util.safe_infer(elt.value, context)
    ...
```

**Verification** on the MWE (patched site-packages astroid):

```
Upper MRO: ['Upper', 'Middle', 'Base', 'object']   # was ['Upper']
Subscript inferred: [<ClassDef.Middle ...>]         # was InferenceError
pylint E1123 enabled: clean                         # was the false positive
```

Trajectory: **divergent for**. Patch fixes the reported false positive without changing the path for non-TypeVarTuple Starred.

## Frontier edges

- **astroid test surface**: write a regression test under `astroid/tests` covering `class Foo[*Ts](Bar[*Ts])` MRO and Subscript inference.
- **pylint test surface**: add a functional regression under `pylint/tests/functional/ext/typing` for E1123 + PEP 695 TypeVarTuple dataclass inheritance.
- **Related #10972**: the issue notes this is likely related. Worth checking whether the same patch resolves it or just shares the surface.
- **`generic_type_assigned_stmts` hack scope**: the `Const(None)` shim is broad. Other call sites that infer through a TypeVarTuple binding may have analogous breakage (e.g. `tuple[*Ts]` annotations consumed by other checkers). Not in scope for this fix; flag for follow-up.

## Reasoning mode table

| Claim | Mode | Confidence |
|---|---|---|
| Bug reproduces on 4.0.5 and on head | Induction | 99% |
| `_infer_sequence_helper` is the failing function | Deduction (traced) | 95% |
| `safe_infer(Shape)` returns `Const(None)`, not `TypeVarTuple` | Deduction (printed) | 99% |
| The cause is `generic_type_assigned_stmts` hack | Deduction (read source) | 95% |
| Patch fixes the reported MWE without unrelated regression | Induction (ran pylint) | 90% — see frontier |

## Pruning log

- Considered: patch `generic_type_assigned_stmts` to yield the TypeVarTuple node itself. **Killed.** `_infer_sequence_helper` would still raise because TypeVarTuple has no `.elts`. Two-site fix, larger blast radius.
- Considered: catch InferenceError in `ClassDef.mro()` and fall back to the unsubscripted base. **Killed.** Too broad — would mask real inference failures in other callers.

## Ship target

Repository: **`pylint-dev/astroid`** (not pylint). Open the PR against astroid `main`. Link this issue (`pylint-dev/pylint#10991`) and #10972 in the PR body. The pylint side needs no change; once astroid ships, pylint's vendored `astroid>=4.x` will pick it up.
