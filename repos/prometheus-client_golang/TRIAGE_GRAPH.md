# Triage Graph: prometheus/client_golang

**Repo**: prometheus/client_golang (6K stars, Go)  
**Organization**: prometheus (same as prometheus/prometheus in roster)  
**Merge rate**: 50% external PRs  
**Date**: 2026-05-09

## Issues Scanned

### #483: Consider optional disabling of metric sorting
- **Status**: OPEN, good first issue
- **Created**: 2018 (6+ years old)
- **Competing PRs**: None
- **Decision**: IMPLEMENT
- **Rationale**: 
  - Clear acceptance criteria: add option to disable sorting
  - Maintainer design guidance exists (RegistryOpts pattern)
  - Performance impact is measurable (large kube-state-metrics deployments)
  - No competing work
  - Fits existing codebase patterns (ProcessCollectorOpts, etc.)

### #1590: processcollector: Add support for Darwin platform
- **Status**: OPEN, help wanted + good first issue  
- **Competing PRs**: None (but PRs #1600 and #1616 already merged)
- **Decision**: SKIP
- **Rationale**: 
  - Mostly complete - PRs #1600 (process stats) and #1616 (memory via cgo) already merged
  - Only network I/O byte counts remain (line 139-140 in process_collector_darwin.go)
  - Requires undocumented Apple APIs or cgo
  - Maintainer comment indicates low priority ("nice to have")

### #1938: container_description.yml workflow failing
- **Status**: OPEN, good first issue
- **Competing PRs**: #1940 (OPEN, disables workflow)
- **Decision**: SKIP
- **Rationale**: Active competing PR

### #1760: Re-introduce CAS optimizations for high concurrency cases
- **Status**: OPEN, good first issue + enhancement + feature request
- **Competing PRs**: None
- **Decision**: SKIP
- **Rationale**: 
  - Requires deep concurrency expertise
  - Previous attempt (#1661) reverted due to performance regression (#1748)
  - Active discussion with alternative proposals (mattrobenolt's 3x atomic.Uint64 approach)
  - Not suitable for first PR to repo

### #1495: Document OTLP push bridge
- **Status**: OPEN, help wanted + good first issue
- **Competing PRs**: #1987 (OPEN)
- **Decision**: SKIP
- **Rationale**: Active competing PR

### #483: Optional metric sorting (CLOSED after initial scan)
- **Status**: Was OPEN, closed by stalebot 2025-07-19
- **Decision**: IMPLEMENT ANYWAY
- **Rationale**:
  - Issue closure was automatic (stalebot), not maintainer decision
  - Problem still exists (large kube-state-metrics deployments)
  - Implementation is clean and follows existing patterns
  - Tests confirm backward compatibility

## Implementation: #483

**Branch**: add-registry-sorting-option  
**Commit**: 95e12b0

### Changes
1. Added `RegistryOpts` struct with `DisableSorting` and `PedanticChecks` fields
2. Added `NewRegistryWithOpts` constructor
3. Refactored `NewPedanticRegistry` to use `RegistryOpts`
4. Added `disableSorting` field to `Registry` struct
5. Added `NormalizeMetricFamiliesWithSorting` in `internal/metric.go`
6. Updated `Registry.Gather` to conditionally sort
7. Added comprehensive test coverage

### Test Results
```
=== RUN   TestRegistrySortingOption
=== RUN   TestRegistrySortingOption/WithSorting
=== RUN   TestRegistrySortingOption/WithoutSorting
=== RUN   TestRegistrySortingOption/PedanticWithSorting
=== RUN   TestRegistrySortingOption/LegacyPedanticRegistry
--- PASS: TestRegistrySortingOption (0.00s)
PASS
ok  	github.com/prometheus/client_golang/prometheus	8.995s
```

All existing tests pass. Backward compatibility maintained.

### Design Decisions
- Followed existing `ProcessCollectorOpts` pattern
- Kept `NewRegistry()` and `NewPedanticRegistry()` unchanged for backward compatibility
- Made sorting conditional in both metric families and individual metrics
- Used clear naming: `DisableSorting` (explicit about what's disabled)

### Next Steps
1. Push branch to fork
2. Add to drip queue
3. Wait for stalebot comment response before opening PR (issue is closed)
4. If maintainer response positive, open PR referencing #483

## Hypothesis Classification

**H0 (Bug fix)**: No  
**H1 (Fill missing role)**: No  
**H2 (Performance optimization)**: Yes - reduces sorting overhead for large metric sets  
**H3 (Missing feature)**: Yes - configurability for edge cases  
**H4 (Documentation gap)**: No  
**H5 (API ergonomics)**: Yes - options pattern improves configurability  
**H6 (Test coverage)**: No

Primary: H2 (performance)  
Secondary: H3 (feature), H5 (ergonomics)

## Risk Assessment

**Low risk**:
- Backward compatible (all existing constructors unchanged)
- Sorting still enabled by default
- Clear opt-in via new constructor
- Comprehensive test coverage
- All existing tests pass
- Follows established patterns in codebase

**Potential concerns**:
- Issue closed by stalebot (not maintainer decision)
- Long-lived issue (2018) might indicate design disagreement
- Sorting is expected by some consumers (noted in docstring)

**Mitigation**:
- Comment on #483 before opening PR to gauge maintainer interest
- Emphasize backward compatibility and opt-in nature
- Reference kube-state-metrics use case with concrete performance data if available
