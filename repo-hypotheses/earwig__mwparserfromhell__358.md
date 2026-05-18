# Hypothesis Graph — earwig/mwparserfromhell#358

PR: [#358 Fix C tokenizer NUL byte truncation](https://github.com/earwig/mwparserfromhell/pull/358) (author: kimjune01)
Referenced issue: [#355](https://github.com/earwig/mwparserfromhell/issues/355) (reporter: gistrec)
Branch: `fix-nul-truncation` · Base: `main` · State: OPEN, CONFLICTING (trivial test-file conflict only)

## Causal chain (confirmed)

The C tokenizer's `Tokenizer_read` returned `'\0'` for both real NUL bytes in input and out-of-bounds reads (EOF). Downstream `!this`/`!last` truthiness checks treated real NUL as EOF, silently truncating input at the first NUL. Python tokenizer used a dedicated `END` sentinel, so behaviors diverged.

Fix: introduce `TOKENIZER_EOF = (Py_UCS4)0x110000` (first invalid Unicode code point), return it from `Tokenizer_read`/`Tokenizer_read_backwards` on OOB, and replace all `!this`/`!last` checks with explicit `== TOKENIZER_EOF` comparisons. Remove `'\0'` from `MARKERS`.

## Graph state

| ID | Hypothesis | Mode | Status | Confidence |
|----|------------|------|--------|------------|
| H₀ | C tokenizer truncates at first NUL byte; PyTokenizer preserves it | induction | **confirmed** | 99% |
| H₁ | Root cause is `Tokenizer_read` conflating `'\0'` with EOF | deduction | **confirmed** | 98% |
| H₂ | Sentinel swap (`0x110000`) + explicit EOF checks fixes the bug | induction | **confirmed** | 97% |
| H₃ | `is_marker(TOKENIZER_EOF)` is now false — could break callers expecting NUL-as-marker | deduction | **killed** (no observable break; remaining callers either short-circuit on EOF earlier or fall through to fail-route via valid[] sentinel) | 90% |
| H₄ | Reordering `handle_end` before `verify_safe` in main parse loop diverges from PyTokenizer ordering | deduction | **partial** — divergence exists in code but is not observable on tested inputs | 75% |
| H₅ | Test suite (1723 tests) still passes on fix branch | induction | **confirmed** | 99% |

## Provenance

- **H₀ perturbation:** built C extension on `main`, ran `CTokenizer().tokenize('a\x00b')` → `'a'`; ran the same on `fix-nul-truncation` → `'a\x00b'`. Bug reproduces on master, fix is correct.
- **H₁:** read `Tokenizer_read` at `tok_support.c:442` — `if (index >= self->text.length) return '\0';`. Reporter's diagnosis matches the source.
- **H₂:** all 4 reported failing inputs (`a\x00b`, `hello\x00world`, `{{a\x00b}}`, `a\x00b\x00c`) now produce identical C and Py output.
- **H₃ analysis:** `is_marker` callsites at `tok_parse.c:1110, 1383, 1406, 2891, 2959` reviewed.
  - L1110 (`Tokenizer_really_parse_entity` loop): EOF falls through `is_marker`, then fails via `valid[j]` null sentinel — same fail-route outcome.
  - L1383 (`Tokenizer_handle_tag_text`): caller `Tokenizer_really_parse_tag` already checks `this == TOKENIZER_EOF` before reaching here.
  - L1406 (`Tokenizer_handle_tag_data`): same guard upstream.
  - L2891 (main loop): EOF short-circuits earlier in the loop, never reaches this branch.
  - L2959: patch explicitly added `last != TOKENIZER_EOF` guard.
- **H₄ analysis:** in `Tokenizer_parse`, the new code checks `this == TOKENIZER_EOF` BEFORE `Tokenizer_verify_safe`, while `tokenizer.py:1413-1417` calls `_verify_safe(this)` BEFORE checking `this is END`. Pre-fix C ran `verify_safe('\0')` which could `return -1` under `FAIL_NEXT` or `TEMPLATE_NAME+FAIL_ON_TEXT`. Post-fix C bypasses verify_safe on EOF.
  - Perturbation: ran 8 unclosed-construct inputs (`{{`, `{{a`, `[[a`, `{{a|`, `{{a}}`, `[[a|`, `<ref`, `<ref name=`) — C and Py produce identical output. Either fail_route(EOF) and handle_end(EOF) unwind equivalently, or the test corpus doesn't reach FAIL_NEXT at EOF. Trajectory: **convergent** on tested inputs.

## Frontier edges (open, non-blocking)

- **F₁ (H₄):** Construct an input that sets `LC_FAIL_NEXT` immediately before EOF and verify C/Py parity. The Python path would `fail_route`; the C path now runs `handle_end`. If outputs match, behavior equivalence is established; if they diverge, the patch needs a follow-up to restore ordering parity.
- **F₂:** Merge conflict in `tests/test_tokenizer.py` is a trivial concurrent test addition (`test_entity_does_not_corrupt_heap` from #356). Resolve by keeping both tests; no semantic conflict.

## Risk assessment

- **Sound diagnosis:** matches reporter's root-cause analysis verbatim; reporter even suggested `0x110000` as the sentinel.
- **Minimal change:** mechanical `!x` → `x == TOKENIZER_EOF` substitution, one sentinel macro, one MARKERS edit. No new control flow except the early EOF return in main loop.
- **Regression coverage:** new parametrized test covers C and Py paths on plain text, mid-string NUL, NUL inside templates, and multiple NULs. Full suite passes.
- **Open question:** the main-loop reordering (F₁) is the one place where C now diverges from Py at the structural level. The 1723-test suite doesn't catch it; either it's truly invariant for EOF, or there's an untested edge case. Worth a one-line probe before merge but not a blocker.

## Reasoning mode summary

| Mode | Claims |
|------|--------|
| Induction (experiment) | H₀ repro, H₂ fix verification, H₅ test pass, F₁ partial probe |
| Deduction (code trace) | H₁ root cause, H₃ callsite audit, H₄ ordering divergence |
| Abduction | (none surviving — initial fix-shape hypothesis was confirmed) |

## Recommendation

Fix is correct and ready to merge. Resolve trivial test conflict against current main. Optional: add one probe input for F₁ to lock in EOF-in-unsafe-context parity, but suite-green on 1723 tests is already strong evidence.
