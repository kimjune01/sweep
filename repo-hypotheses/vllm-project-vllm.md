# Triage Graph: vllm-project/vllm (kimjune01)

**Scan date:** 2026-05-09
**Mode:** dry-run

## Scan Table

| # | Title | State | Score | Effort | Signal | Status |
|---|-------|-------|-------|--------|--------|--------|
| — | disable_any_whitespace rejects auto backend | No issue filed | 5/10 | Small (~20 lines Python) | Config validation gap | IMPLEMENTED |

## disable_any_whitespace + auto backend

### Root Cause

`StructuredOutputsConfig._validate_structured_output_config` checks `self.backend not in ("xgrammar", "guidance")` but `auto` is the default backend and resolves to one of those two at runtime. Users setting `disable_any_whitespace=True` with the default backend get a spurious `ValueError`.

### Fix (~20 lines across 2 files + test file)

1. **`vllm/config/structured_outputs.py`**: Add `"auto"` to the validator allow-list. Update docstring to mention auto.
2. **`vllm/sampling_params.py`**: When `auto` falls back to `outlines` (unsupported), emit a `logger.warning` that the flag will be ignored — prevents silent data loss.
3. **`tests/config/test_structured_outputs_config.py`**: 6 unit tests covering auto/xgrammar/guidance (pass) and outlines/lm-format-enforcer (reject) and default value.

### Review notes

- **Codex suggestions applied:** docstring updated, warning on outlines fallback added, tests added.
- **No competing PRs** found.
- **No existing issue** — discovered by reading config validation code.

### Files changed

- `vllm/config/structured_outputs.py`
- `vllm/sampling_params.py`
- `tests/config/test_structured_outputs_config.py` (new)
