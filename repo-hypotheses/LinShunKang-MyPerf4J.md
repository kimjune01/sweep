# Triage Graph: LinShunKang/MyPerf4J

**Repo**: LinShunKang/MyPerf4J (Java profiler, 3.5K stars)  
**Triage Date**: 2026-05-10  
**First Contribution**: Yes

## Issue Analysis

### Investigated Issues

1. **#115**: Grafana dashboard host filter not working
   - **Type**: Configuration/dashboard issue
   - **Ruling**: Not a code fix - Grafana dashboard configuration
   - **Action**: Skip

2. **#114**: How to configure Grafana alerts
   - **Type**: Question/documentation
   - **Ruling**: Not actionable code fix
   - **Action**: Skip

3. **#110**: Add annotation-based filtering for methods
   - **Type**: Feature request
   - **Maintainer**: Interested but busy, asked for contributor
   - **Ruling**: Too large for first PR
   - **Action**: Skip

4. **#90**: File.renameTo() and setReadOnly() issues on Windows
   - **Type**: Bug
   - **Competing PR**: #91 (closed without explanation Nov 2025)
   - **Codex Review**: Fix requires complex DOS readonly attribute handling, retry logic
   - **Ruling**: Too risky for first PR (unclear why #91 was rejected)
   - **Action**: Skip main issue, extract ConfigKey toString() fix from discussion

5. **#40**: JVM object allocation monitoring
   - **Type**: Large feature request
   - **Ruling**: Too large
   - **Action**: Skip

### Selected Fix

**ConfigKey toString() improvement** (mentioned in #90 discussion by JiaRG)
- **Problem**: ConfigKey objects print memory addresses instead of key values when logged
- **Solution**: Add toString() override to show key and legacyKey fields
- **Files Changed**: `MyPerf4J-Base/src/main/java/cn/myperf4j/base/config/ConfigKey.java`
- **Codex Review**: Approved, conventional implementation
- **Size**: 8 lines added
- **Risk**: Minimal - pure diagnostic improvement

## Implementation

### First Attempt (GATE_FAIL)
**Branch**: `fix-windows-file-rename`  
**Commit**: d9a4259  
**Status**: Failed drip gate  
**Failure Reason**: 
- Build-breaking typo: `<source>` used twice in Maven compiler config instead of `<source>` + `<target>`
- JMH migration invalidates historical benchmarks (semantic change)
- Scope too broad: 539 lines covering Maven plugin management, JMH migration, AND ConfigKey toString

### Second Attempt (READY)
**Branch**: `fix-configkey-tostring`  
**Commit**: 532555e "Add toString() to ConfigKey for readable log output"  
**Status**: Ready for drip push

### Changes
- Added toString() method to ConfigKey class (8 lines)
- Returns formatted string with both key and legacyKey values
- Improves debuggability when ConfigKey objects appear in logs
- **Codex Review**: Approved toString() addition, noted pre-existing missing equals/hashCode (out of scope)
- **Gemini Review**: Confirmed syntax correct, immutability good, equals/hashCode missing is pre-existing

## Decision Rationale

Chose smallest, safest fix for first contribution:
- Issue #90 discussed by active contributor (JiaRG has merged PR #88)
- ConfigKey toString() is a code quality improvement, not a bug fix
- No behavior changes, only logging improvement
- Follows Java conventions (IDE-generated style)
- No tests needed for toString()

Maintainer is active (PR #116 open for 4.0 release). Targeting merge before major version.

## Hypothesis Updates

- **H0 (Cold start barrier)**: Testing with minimal fix approach
- **H2 (Change type)**: Code quality improvement, not bug fix
- **H5 (Trust building)**: First contribution, keeping it trivial
