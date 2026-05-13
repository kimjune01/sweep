# Triage Graph: jmpsec/osctrl

**Repository**: jmpsec/osctrl (498★, Go - osquery management)  
**Issues scanned**: 22 open issues  
**Date**: 2026-05-11

## Selected Issues

### #57: Quick-enroll for OSX does not reload osqueryd
- **Status**: Fixed (queued)
- **Type**: Bug
- **Scope**: Small, single-file change
- **Branch**: fix/osx-quick-enroll-reload
- **Commit**: 390e0f18

**Problem**: When re-enrolling an OSX node where osqueryd is already running, the quick-add script fails with "service already loaded" error. The script uses `launchctl unload` alone, which doesn't stop a running service.

**Solution**: Added `launchctl stop` before `launchctl unload` in the `stopOsquery()` function for Darwin platform. This ensures the service is fully stopped before attempting to reload.

**Files changed**:
- `pkg/environments/scripts.go` (1 line added)

**Tests**: All existing tests pass (`go test ./pkg/environments/...`)

**Devil's advocate**: ✓ Change is minimal and follows launchctl best practices. The stop-then-unload pattern is the correct approach for macOS services.

---

### #634: Race condition for function IncExecution and IncError
- **Status**: Fixed (queued)
- **Type**: Bug (concurrency issue)
- **Scope**: Small, single-file change
- **Branch**: fix/race-condition-inc-execution-error
- **Commit**: 8e4108cf

**Problem**: Read-modify-write race condition in query counter updates. When multiple goroutines call IncExecution/IncError concurrently:
1. Thread A reads: executions = 5
2. Thread B reads: executions = 5 (same value)
3. Thread A updates: executions = 6
4. Thread B updates: executions = 6 (should be 7, lost update)

**Solution**: Replaced read-modify-write pattern with atomic SQL operations using `gorm.Expr("executions + ?", 1)`. The database now performs: `UPDATE distributed_queries SET executions = executions + 1 WHERE ...`

**Files changed**:
- `pkg/queries/queries.go` (15 lines changed, -11/+15)

**Tests**: All existing tests pass (`go test ./pkg/queries/...`)

**Devil's advocate**: ✓ The fix is correct and uses standard GORM atomic update patterns. The change also improves error handling by checking RowsAffected and returning a meaningful error if the query isn't found.

---

## Declined Issues

### #2: Change setting `inactive_hours` to be set by environment
- **Reason**: Larger scope than initial two fixes. Would require updating ~15 call sites across multiple services.
- **Complexity**: Medium - the infrastructure exists (SettingValue already has EnvironmentID field), but all callers pass NoEnvironmentID.
- **Status**: Deferred - good candidate for future work after establishing standing.

### #774, #738, #704, #683: Permission/RBAC enhancements
- **Reason**: Large feature requests requiring significant design work.

### #635: Performance problems with large node sets (10,000+ nodes)
- **Reason**: Active development by maintainer and contributor. Recent discussion indicates complex solution in progress.

### #529: Run distributed query/carve based on custom tags
- **Reason**: Feature partially implemented (PR #713), caching work still needed. Active maintainer involvement.

### #641: Refactor logging package
- **Reason**: Architectural change requiring design discussion.

### #637: Implement node caching
- **Reason**: Performance enhancement, larger scope.

### #256: Split backend connection by read and write
- **Reason**: Large architectural change with active discussion by contributors.

---

## Repository Insights

**Maintainer**: @javuto (active, responsive to PRs)
**Contributors**: @zhuoyuan-liu (active contributor, performance focus)
**Recent activity**: High - multiple recent merges, active issue discussions
**Test coverage**: Good - tests exist for modified packages
**Code quality**: Clean Go, uses GORM ORM, follows Go conventions

**Merge patterns**:
- Bug fixes merge quickly
- Performance improvements reviewed carefully
- Feature requests require discussion

**Standing strategy**: Start with bug fixes to establish reliability, then tackle small enhancements.
