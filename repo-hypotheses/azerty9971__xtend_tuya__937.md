# Hypothesis Graph: azerty9971/xtend_tuya#937

**Issue**: Sometimes a reload will crash. `AttributeError: 'ConfigEntry' object has no attribute 'runtime_data'`
**Reporter**: pjmpessers
**Date**: 2026-05-18
**Reproducer**: User reloads xtend_tuya hourly to keep wifi access panel responsive; ~33 occurrences seen across one workday since upgrading to v4.4.7.

## H₀ — Direct trace from stack

The traceback names the failing line precisely:

```
File "/config/custom_components/xtend_tuya/util.py", line 82, in get_config_entry_runtime_data
    runtime_data = entry.runtime_data
AttributeError: 'ConfigEntry' object has no attribute 'runtime_data'
```

The call chain:
- `__init__.async_setup_entry` →
- `multi_manager.setup_entry` →
- `tuya_sharing/init.py:setup_from_entry` →
- `_init_from_entry` →
- `tuya_sharing/util.py:get_overriden_tuya_integration_runtime_data` →
- `util.py:82:get_config_entry_runtime_data` — accesses `entry.runtime_data` unguarded.

**Trajectory**: Divergent — the stack unambiguously identifies one line. No measurement needed.
**Reasoning mode**: Deduction (read the code, traced the stack).
**Confidence**: 99%.

## H₁ — Why is `runtime_data` unset on a HA ConfigEntry?

In Home Assistant, `ConfigEntry.runtime_data` is an instance attribute set inside `__async_setup_with_context` after `async_setup_entry` completes. Before setup completes, or after the entry has been unloaded/teardown'd, the attribute does not exist (HA does not pre-initialize it — `getattr` returns `AttributeError`, not `None`).

`get_config_entry_runtime_data` is called on the **overridden Tuya integration entry** (`DOMAIN_ORIG`), not xtend_tuya's own entry. `get_overriden_config_entry` matches an entry from the original `tuya` domain by title. That entry's lifecycle is independent: it can be loading, failed, unloaded, or mid-reload while xtend_tuya's reload runs.

The reporter reloads every hour. The original Tuya integration entry exists (since the override matched by title), but at the moment of xtend_tuya's reload, that entry is in a state where `runtime_data` hasn't been set (or was deleted on unload). Race window during hourly reload.

**Trajectory**: Divergent — the HA framework's documented contract matches the symptom.
**Reasoning mode**: Deduction from HA core's `config_entries.py` semantics.
**Confidence**: 95%.

## H₂ — Is this regression specific to v4.4.7?

Reporter says: "Before this wasn't a problem. But it does now from v4.4.7."

`get_config_entry_runtime_data` was added recently (visible in the only commit in shallow history). It centralizes runtime_data access that was previously inline. Other call sites in the codebase (`humidifier.py`, `switch.py`, etc.) access `entry.runtime_data` on **xtend_tuya's own entry** during platform setup — that entry's `runtime_data` is set by `__init__.py:123` before platforms initialize, so those sites are safe.

The new path uniquely accesses **another integration's** ConfigEntry, where the lifecycle is not synchronized. The refactor introduced cross-integration runtime_data access without a defensive guard.

**Trajectory**: Convergent — consistent with the regression claim and the centralization story.
**Reasoning mode**: Deduction + induction (other call sites surveyed).
**Confidence**: 90%.

## Provenance

- File: `custom_components/xtend_tuya/util.py` lines 77-91.
- `git blame` line 82: commit `a7cda939` ("Changed Tuya link", 2026-05-02) replaced the prior `hasattr(entry, "runtime_data") or entry.runtime_data is None` branch with unconditional `entry.runtime_data` access. The fallback path (`hass.data[domain][entry_id]`) was removed at the same time. The unguarded access is the regression; the fallback removal looks intentional (HA no longer stores runtime there).
- Manifest version `4.4.7` (current `HEAD` of main). Matches reporter's "from v4.4.7" claim exactly.
- No existing PR (gh search "runtime_data" → only PR #930, the merged battery fix; no open work on this).
- No existing issue with the same fingerprint (issue search "runtime_data" → only #937).

## Fix applied (Phase 5)

Edited `custom_components/xtend_tuya/util.py:82` — replaced `runtime_data = entry.runtime_data` with `runtime_data = getattr(entry, "runtime_data", None); if runtime_data is None: return None`. Minimal restoration of the guard removed in `a7cda939`. No tests in repo to update.

## Fix shape

Guard the access. The function's contract already permits returning `None` (caller `_init_from_entry` already branches on `if tuya_integration_runtime_data:`). Use `getattr` to handle the missing-attribute case without a try/except:

```python
def get_config_entry_runtime_data(
    hass: HomeAssistant, entry: tuya_coordinator.TuyaConfigEntry | shared.XTConfigEntry, domain: str
) -> ConfigEntryRuntimeData | None:
    if not entry:
        return None
    runtime_data = getattr(entry, "runtime_data", None)
    if runtime_data is None:
        return None
    device_manager = runtime_data.manager
    ...
```

Minimal change. Returns `None` on the race; caller already handles `None` (falls through to the "XT as a standalone integration" branch at `tuya_sharing/init.py:166`).

## Risk

- **Correctness**: when the override entry is loading/unloaded, xtend_tuya transparently falls back to standalone mode for that reload. Next reload — once Tuya's entry has finished setup — re-establishes the override. This matches the user's observed pattern ("sometimes" a reload crashes).
- **Scope**: one-line change. No behavior change when `runtime_data` is set normally.
- **No tests**: this repo has no test suite (typical HA custom integration). Verification is by inspection + reading the HA framework contract.

## Frontier

- All edges classified. The diagnosis is mechanical and the fix is minimal. Proceed to prework + ship.

## Reasoning mode table

| Hypothesis | Mode | Confidence |
|---|---|---|
| H₀ failing line | deduction (stack trace) | 99% |
| H₁ ConfigEntry lifecycle race | deduction (HA framework contract) | 95% |
| H₂ regression specific to v4.4.7 | deduction + induction | 90% |
