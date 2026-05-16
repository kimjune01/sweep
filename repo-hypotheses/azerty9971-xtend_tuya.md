# Triage Graph: azerty9971/xtend_tuya

**Repo**: azerty9971/xtend_tuya (Home Assistant Tuya integration)  
**Stars**: 322  
**Language**: Python  
**Open Issues**: 32  
**Triage Date**: 2026-05-11

## Repository Context

Home Assistant custom integration for Tuya devices. Active maintainer (azerty9971) responsive on issues. No formal test suite (typical for HA custom components). Recent focus on fixing device class ambiguity warnings and unit normalization.

## Issues Investigated

### ✅ #915 - Multiple possible device class for unit % on battery sensors
**Status**: QUEUED (fix/battery-device-class-ambiguity)  
**Hypothesis**: H2 (standing-first, clean bug fix)  
**Type**: Bug - device class ambiguity  
**Complexity**: Low  
**Branch**: fix/battery-device-class-ambiguity  
**Files Changed**: const.py (+6 lines)

**Problem**: When battery_state, battery_value, battery_power, va_battery, residual_electricity, or wireless_electricity dpcodes report unit "%", the system can't disambiguate between battery/humidity/moisture/power_factor device classes. This causes warning logs and None device class.

**Fix**: Added 6 battery-related dpcodes to DPCODE_PREFERED_DEVICE_CLASS dict:
```python
"battery_power": "battery",
"battery_state": "battery",
"battery_value": "battery",
"residual_electricity": "battery",
"va_battery": "battery",
"wireless_electricity": "battery",
```

**Validation**:
- All 6 dpcodes are already defined in const.py with battery semantics
- All 6 have explicit descriptors in sensor.py with SensorDeviceClass.BATTERY
- Fix makes generic sensor path consistent with explicit descriptors
- Zero risk of breaking non-battery devices (dpcode names are unambiguous)

**Devil's Advocate**: Could any of these dpcodes be used for non-battery purposes?
- Answer: No. All have explicit battery sensor descriptors in sensor.py, and semantic names are clearly battery-related.

**Commit**: d4e47e23

---

### ⏸️ #877 - Multiple possible device class for unit kWh (add_ele)
**Status**: ALREADY FIXED  
**Reason**: "add_ele": "energy" already exists in DPCODE_PREFERED_DEVICE_CLASS (line 1209). Maintainer confirmed "The warning will be fixed in the next release."

---

### ⏸️ #919 - Non-standard units (kw.h, S, PF) break statistics
**Status**: SKIPPED - maintainer working on it  
**Reason**: User reported having fix, maintainer responded asking for raw logs, said they've "already added the ones that I could figure out and they should be fixed in the next release."

---

### ⏸️ #913 - Presence sensor not recognized as occupancy entity
**Status**: SKIPPED - breaking change  
**Type**: Breaking change / needs design discussion  
**Complexity**: Medium  
**Reason**: Would require changing BinarySensorDeviceClass.MOTION to OCCUPANCY for PRESENCE_STATE dpcode. This is a behavioral change that could affect existing automations. Needs maintainer input on migration strategy.

**Technical Detail**: HA 2026.5 occupancy triggers require BinarySensorDeviceClass.OCCUPANCY, not MOTION. Current code uses MOTION for presence sensors.

---

### ⏸️ #912 - V4.4.7 Cover issue 2 gang switch
**Status**: SKIPPED - regression investigation  
**Reason**: Regression in 4.4.7 configuration system. Requires understanding config changes and multi-entity configuration flow. Too complex for standing-first PR.

---

### ⏸️ #918 - Energy meter unavailable after 4.4.7
**Status**: ALREADY FIXED  
**Reason**: User confirmed "It is working again with 4.4.8 beta-1"

---

### ⏸️ #802 - Battery status animation (dynamic icons)
**Status**: SKIPPED - feature enhancement  
**Reason**: Feature request for dynamic battery icons based on level. Not a bug. Standing first.

---

### ⏸️ #608 - Question about last_updated/last_changed
**Status**: SKIPPED - question/documentation  
**Reason**: User question about HA semantics, not a code bug.

---

### ⏸️ #606 - HVAC Mini Split only shows cooling mode
**Status**: SKIPPED - complex feature  
**Type**: Missing feature - mode enum mapping  
**Complexity**: Medium-High  
**Reason**: Requires climate platform investigation, mode enum to HVAC mode mapping. User has diagnostic file. Good second PR after earning standing.

## Denylist

None.

## Evidence Summary

### What Worked
- Clean bug fix with mechanical solution (add to existing dict)
- Fix aligns with existing explicit descriptors (consistency win)
- Reported issue with clear error message
- Low risk, high value

### What Didn't Work
- Many issues are already being addressed by maintainer
- Several issues require design discussions (breaking changes)
- No test suite makes TDD harder (but typical for HA custom components)

### Repository Patterns
- Active maintainer, responsive to issues
- "Awaiting fix confirmation" label used for in-progress fixes
- Users often provide diagnostic files (good for debugging)
- Integration inherits from ha-tuya-integration with extensions

## Next Steps

1. **Immediate**: Push fix/battery-device-class-ambiguity to fork, wait for drip
2. **After #915 merges**: Consider #606 (HVAC modes) or #913 (occupancy, with maintainer discussion)
3. **Watch**: #919 (unit normalization) - maintainer working on it, might conflict with our changes

## Hypothesis Validation

**H2 (Standing-first)**: One clean bug fix queued. Validates hypothesis that mechanical fixes to reported bugs are lowest-friction entry point.

**H0 (Acceptance barrier)**: TBD - need to see if maintainer accepts. Risk: low (aligns with existing code, fixes reported warning).

**H5 (Code quality)**: Fix improves consistency (generic path now matches explicit descriptors). No broader quality debt addressed.
