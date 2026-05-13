# Triage Graph: apache/airflow

## Scan (2026-05-09)

User: kimjune01. 40K+ stars, Python workflow orchestrator.
Status: First contribution. Bug fix, test included.

### Triaged issues

| # | Score | Signal | Title | Fix branch | Gate | Status |
|---|-------|--------|-------|------------|------|--------|
| 65375 | 4 | Bug, FK constraint failure on role deletion | FAB role deletion fails with IntegrityError on migrated DBs | `fix/fab-role-deletion-fk-65375` | test: PASS | READY |

### Fix details

**#65375** (2 files, +52 -3)
- File: `providers/fab/src/airflow/providers/fab/auth_manager/security_manager/override.py`
- Change: `delete_role` now explicitly deletes from `assoc_permission_role`, `assoc_user_role`, and `assoc_group_role` before deleting the role row
- Root cause: Databases migrated from older Airflow versions may lack CASCADE on FK constraints. The old code did `delete(Role).where(Role.name == role_name)` which left dangling FK rows
- Also fixed: Uses `self.role_model` instead of hardcoded `Role` class, matching the pattern used elsewhere in the security manager
- Test: Verifies 4 execute calls (3 association deletes + 1 role delete) and commit

### Competing PRs

None found for #65375.
