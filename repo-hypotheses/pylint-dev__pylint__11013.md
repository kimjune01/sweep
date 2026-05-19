# pylint-dev/pylint#11013 — C0103 false positive on `TypeAlias` nested in `TYPE_CHECKING`

## H₀: Bug reproduces on the minimal snippet from the issue body

- **Null**: Snippet (with `from typing import TypeAlias`) emits C0103 under `const-naming-style=UPPER_CASE`.
- **Perturbation**: Ran `pylint --rcfile=<const=UPPER_CASE> --disable=all --enable=C0103 repro.py` on v4.0.5 *and* main.
- **Result**: No warning either time. **H₀ killed — divergent.**
- **Edge**: The issue body's snippet is not the actual repro. The user's real code (linked weaver project) must differ. Pull the actual file.

## H₁: The real repro uses `from typing_extensions import TypeAlias`

- **Perturbation**: Fetched `weaver/datatype.py` from the dependabot branch the user cited. Line 138-139 sit inside a `TYPE_CHECKING` block that imports `TypeAlias` from **`typing_extensions`**, not `typing`. Constructed a minimal repro using `typing_extensions.TypeAlias`.
- **Result on v4.0.5 and main**: Emits `C0103 Constant name ...` on `AuthenticationType: TypeAlias = "..."`. **Divergent — confirmed.**

## H₂: `_assigns_typealias` only recognizes the `typing` qname

- `pylint/checkers/base/name_checker/checker.py:700-718` checks `inferred.qname() == "typing.TypeAlias"` only. `TYPE_VAR_QNAMES` (line 53+) already accepts both `typing.X` and `typing_extensions.X` for TypeVar/ParamSpec/TypeVarTuple — the TypeAlias path was just missed.
- **Naive fix**: add `"typing_extensions.TypeAlias"` to the qname checks. **Killed by induction** — still reproduces. Trace via astroid shows `safe_infer(annotation)` returns `Uninferable` for `typing_extensions.TypeAlias` even with the package installed, so the qname branch is never entered.

## H₃: Astroid cannot infer `typing_extensions.TypeAlias`; need a name-lookup fallback

- **Perturbation**: Used `astroid.Name.lookup()` on the annotation directly — returns the `ImportFrom` node showing `modname == "typing_extensions"`, `names == [("TypeAlias", None)]`. Reliable even when `safe_infer` fails.
- **Fix**: After the existing inference branch in `_assigns_typealias`, fall back to a name-based lookup: if the annotation is `Name("TypeAlias")` and lookup resolves to an `ImportFrom` of `TypeAlias` from `typing` or `typing_extensions`, treat as TypeAlias.
- **Result**: Repro now clean under UPPER_CASE const style. 64 name+typealias functional tests pass. **Confirmed — convergent.**

## Provenance

- `git blame` on the qname check: untouched since the original TypeAlias handling. The `typing_extensions` gap is an omission, not a deliberate exclusion (TypeVar/ParamSpec handle both qnames in `TYPE_VAR_QNAMES`).
- Astroid's failure to infer `typing_extensions.TypeAlias` is the upstream cause; the name-lookup fallback is robust to either resolution path.

## Diff shape

- `pylint/checkers/base/name_checker/checker.py` — accept `typing_extensions.TypeAlias` in the qname check, plus a name-lookup fallback when inference fails.
- `tests/functional/t/type/typealias_naming_style_typing_extensions.{py,txt}` — new fixture: `GoodName: TypeAlias = ...` clean, `BadNAME: TypeAlias = ...` flagged as type-alias style violation (not constant).
- `doc/whatsnew/fragments/11013.false_positive` — towncrier entry, closes #11013.

## Verification

- Fail-on-main: confirmed C0103 on minimal `typing_extensions.TypeAlias` repro on `main` before the fix.
- Pass-with-fix: same repro clean after fix.
- Regression sweep: `pytest tests/test_functional.py -k "typealias or name"` → 64 passed, 0 failed.

## Reasoning mode table

| H  | Mode      | Confidence |
|----|-----------|-----------:|
| H₀ | Induction (ran repro) | 95% (killed) |
| H₁ | Abduction + induction (fetched real source, re-ran) | 95% (confirmed) |
| H₂ | Deduction (read checker code) → induction (tested naive fix) | 95% (killed) |
| H₃ | Deduction (astroid lookup API) → induction (applied + test suite) | 95% (confirmed) |

## H₄: Reinvestigation — does the functional test fail-on-master under CI's astroid pin?

- **Perturbation**: pylint's CI pins `astroid==4.2.0b3`. Re-ran `pytest -k typealias_typing_extensions` with this pin against (a) HEAD + fix and (b) HEAD with the checker change reverted (test file kept).
- **Result**: **both pass.** With astroid 4.2.0b3, the typing_extensions brain plugin makes `safe_infer(annotation)` for `typing_extensions.TypeAlias` return a `ClassDef` whose qname is `typing.TypeAlias`. Master's narrow check matches; the test sees the expected "Type alias name" violation either way.
- **Trajectory**: convergent against the fail-on-master invariant. The fix is correct (verified with `astroid==4.0.4`, the reporter's version) but its functional test cannot differentiate master from fix on the CI environment.
- **Implication**: pylint main already requires `astroid>=4.2.0b3`, which contains the upstream fix. Any user who upgrades pylint will pick up the new astroid floor and stop seeing the bug.
- **Edge**: ship the fix anyway as defensive hardening for users pinned to older astroid (reporter is on `astroid==4.0.4`), or close with "fixed via astroid pin." The fix is a small, well-scoped backstop; recommendation is ship.

## Reasoning mode addendum

| H  | Mode | Confidence |
|----|------|-----------:|
| H₄ | Induction (matrix test fix×{master,fix} × astroid×{4.0.4, 4.2.0b3}) | 95% (confirmed — invariant broken under CI pin, fix correct under reporter pin) |
