# pylint-dev/pylint#10982 — Python 3.15 compatibility (test fixtures)

## H₀ — the issue is well-scoped and reporter-validated

- **Hypothesis**: The change is mechanical fixture updates for tests that drift on Python 3.15. No production-code logic change required.
- **Perturbation**: Read the issue body. Reporter (frenzymadness) supplied a full diff. Maintainer (Pierre-Sassoulas) responded with one specific correction: skip the `unspecified-encoding` parts because #10800 already disables W1514 for `py-version >= 3.15`.
- **Trajectory shape**: Convergent. Reporter + maintainer agree on the shape; only one carve-out.
- **Status**: Confirmed.
- **Edge**: Apply the reporter's diff minus the unspecified-encoding bits.

## H₁ — what actually breaks on 3.15

Three independent fixture failures, one root cause each.

### H₁ₐ — `deprecated_methods_py36`
- **Diagnosis**: `SourceFileLoader.load_module` / `SourcelessFileLoader.load_module` are removed in 3.15. The test file imports them and asserts `[deprecated-method]`; on 3.15 astroid can't find the methods so the message never fires (or worse, the import itself fails).
- **Fix shape**: `max_pyver=3.14` in a new `.rc` so the test is skipped on 3.15+.
- **Status**: Applied.

### H₁ᵦ — `no_name_in_module` ElementTree
- **Diagnosis**: `xml.etree.ElementTree.nonexistent_function()` no longer raises `no-member` on 3.15. (Reporter says this comes from astroid pylint-dev/astroid#3032 — likely the brain stops over-eagerly inferring missing attributes on ElementTree.) The other 11 expected messages still fire.
- **Fix shape**: Mark the two ElementTree lines `<3.15: [no-member]` and add `no_name_in_module.315.txt` with the same expectations minus those two.
- **Status**: Applied.

### H₁ᵧ — `unspecified_encoding_py38` (carve-out by maintainer)
- **Original reporter patch**: add `.315.txt`, conditionalize `test_minimal_messages_config_enabled`.
- **Why dropped**: Pierre-Sassoulas — "should be disabled on 3.15 as per #10800". Verified: `pylint/checkers/stdlib.py:583` has `{"maxversion": (3, 15)}`; `tests/testutils/data/m/minimal_messages_config.py` already has `# -1:<3.15: [unspecified-encoding]`. The existing `py38.rc` pins `py-version=3.8` so the message will still emit on 3.15 runtime — no fixture change needed.
- **Status**: Killed. Skipping per maintainer.

## Provenance check (Phase 2.5)

- **#10800** (Mehraz Hossain Rumman, merged 2026-01-11 as `7b73bfded`): adds `maxversion=(3,15)` to W1514. Touches `stdlib.py`, `unspecified_encoding_py315.{py,rc}`, `unspecified_encoding_py38.rc`, `minimal_messages_config.py`. Maintainer's correction is correct: this PR is the load-bearing mechanism.
- **`pylint/message/message_definition.py:75 may_be_emitted`**: returns False when `maxversion <= py_version`. Default `py-version` (`base_options.py:358`) is `sys.version_info[:2]`, so on 3.15 runtime W1514 is disabled by default — which is exactly why the reporter saw 3.15 test drift.
- **`pylint/testutils/constants.py:25 _EXPECTED_RE`** + `lint_module_test.py:178`: the `<3.15:` comment marker is parsed against `sys.version_info` at runtime, so the `.py` edits are properly gated.
- **`pylint/testutils/functional/test_file.py:105 expected_output`**: picks the `.315.txt` fixture when `_CURRENT_VERSION >= (3,15)`, falls back to `.txt` otherwise. The new `.315.txt` is dormant on 3.11/3.14, active on 3.15.

## Reasoning mode table

| Claim | Mode | Confidence | Evidence |
|-------|------|-----------:|----------|
| `.315.txt` activates only on 3.15 | Deduction | 95% | `test_file.py:105-119` reading |
| `<3.15:` marker is gated by runtime sys.version_info | Deduction | 95% | `lint_module_test.py:178-183` + `constants.py:25-31` |
| W1514 disabled on 3.15 by default | Deduction | 95% | `message_definition.py:75-81` + `base_options.py:358` |
| `max_pyver=3.14` skips test on 3.15+ | Deduction | 95% | `test_file.py:27,52` + `testoptions` parsing |
| All four tests still pass on Python 3.11 | Induction | 99% | `pytest tests/test_functional.py -k 'no_name_in_module or deprecated_methods_py36 or unspecified_encoding'` → 4 passed |
| Tests will pass on 3.15 | Abduction | 75% | Reporter validated locally; can't reproduce without Python 3.15 in container |

## Frontier edges

- **3.15 runtime verification**: not run locally (sweep-tester ships Python 3.11). Risk that reporter's 3.15 diff was wrong about the exact set of `no-member` outputs — but reporter is a Fedora pylint packager working on 3.15 ahead of beta, so high prior on correctness. CI on the PR will exercise 3.15 if/when pylint adds it to the matrix.

## Pruning log

- H₁ᵧ killed by maintainer's pre-existing #10800; saved a meaningless `.315.txt` and an unnecessary `is_message_enabled` conditional in `test_functional_testutils.py`.
