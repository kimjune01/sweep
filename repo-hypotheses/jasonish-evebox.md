# Triage Graph - jasonish/evebox

## Issues Scanned (14 total)
- #349: Missing Sensors for Filtering (Open) - Regression between 0.18.x and 0.21.x, requires understanding sensor indexing logic
- #316: SQLite state in DB dump (Open) - Previously investigated and fixed
- #237: CLI Default Time Range (Open) - **FIXED** - Straightforward CLI enhancement
- #313: Rethink time selector (Open) - Design issue filed by maintainer, requires UX decisions
- #321: pcap filename chooser (Open) - UI enhancement for pcap filename generation
- #360: API for SensorName Alerts (Open) - Documentation request, maintainer already provided response
- #296: Add links for rule references (Open) - Feature request
- #258: Date based retention policy (Open) - Elasticsearch feature request
- #190: Support Security Onion schema (Open) - Schema compatibility feature
- #167: User-Agent parsing (Open) - Feature request
- #126: Integration with Virus Total (Open) - External service integration
- #88: Notes for IPs/subnets (Open) - Feature request
- #87: Stored Default Inbox View (Open) - UI feature request
- #21: Improved dumpy integration (Open) - Old feature request from 2016

## Investigated: #316 SQLite state in DB dump
- **Problem**: `evebox sqlite dump` only exported the `source` column (the raw Suricata EVE JSON), losing EveBox-specific state like `archived`, `escalated`, and `history` which are stored in separate columns in the SQLite schema.
- **Reproduction**:
  1. Load an event: `evebox sqlite load --input repro.json repro.sqlite`
  2. Manually set state: `sqlite3 repro.sqlite "UPDATE events SET archived = 1, escalated = 1;"`
  3. Dump: `evebox sqlite dump repro.sqlite`
  4. Observed: Output JSON lacked `archived` or `escalated` flags.
- **Fix**:
  - Modified `src/cli/sqlite/mod.rs` to select `archived`, `escalated`, and `history` columns.
  - Injected these values into the `source` JSON under the `evebox` key.
  - Modified `src/sqlite/importer.rs` to handle these fields when loading events back into the database.
  - Added support for `escalated` and `history` in `SqliteEventSink`, which were previously missing even for regular imports.

## Verification Results
- Full dump/load cycle verified:
  ```bash
  evebox sqlite dump repro.sqlite > dump.json
  evebox sqlite load --input dump.json repro2.sqlite
  sqlite3 repro2.sqlite "SELECT archived, escalated, history FROM events;"
  ```
- Result: `1|1|[{"action":"escalated","user":"admin"}]` (All state preserved).

## Investigated: #237 CLI Default Time Range

### Problem
Users in oneshot or training environments want to set the default time range to "all" instead of manually selecting it each time. The default was hardcoded to "24h" in the API layer.

### Reproduction
1. Start evebox server: `evebox server --sqlite`
2. Query `/api/config` endpoint
3. Observe: `"defaults": {"time_range": null}`
4. Frontend uses hardcoded "24h" default in AggParams

### Solution
Added `--default-time-range` CLI option to the server command that:
1. Accepts any valid time range format (e.g., "24h", "7d", "all")
2. Stores the value in `ServerContext.defaults.time_range`
3. Exposes it via `/api/config` endpoint for frontend consumption

**Files changed:**
- `src/bin/evebox.rs`: Added CLI argument `--default-time-range`
- `src/server/main.rs`: Read config value and set `context.defaults.time_range`

### Verification
Tested three scenarios:
1. **No argument**: Returns `{"defaults": {"time_range": null}}`
2. **`--default-time-range all`**: Returns `{"defaults": {"time_range": "all"}}`
3. **`--default-time-range 7d`**: Returns `{"defaults": {"time_range": "7d"}}`

All tests passed. The infrastructure was already in place (Defaults struct, API endpoint), just needed wiring from CLI to context.

### Branch: `fix/issue-237-default-time-range`
Commit: `f3d5e655`

## Other Issues Evaluated

### #349 - Missing Sensors for Filtering
**Status**: Not pursued  
**Reason**: Regression between versions involving sensor indexing. Requires deep understanding of:
- How sensors are indexed from EVE events (host field)
- Differences in ingestion between 0.16.x, 0.18.x, and 0.21.x
- Filebeat compatibility issues
Maintainer is actively troubleshooting with the reporter. Would need reproduction case.

### #313 - Rethink time selector
**Status**: Not pursued  
**Reason**: Design issue filed by maintainer (Jason Ish) himself. Involves UX trade-offs:
- Timeout vs. forced time boxing
- Different solutions for different views (inbox vs. reports)
- Performance implications for SQLite vs. Elasticsearch
This is a feature enhancement requiring design decisions, not a straightforward bug fix.

### #360 - API for SensorName Alerts
**Status**: Not pursued  
**Reason**: Documentation request. Maintainer already provided comprehensive response with API parameters table. Could be addressed by adding to README or creating API docs, but not a bug fix.

### #321, #296, #258, #190, #167, #126, #88, #87, #21
**Status**: Not pursued  
**Reason**: All are feature requests or enhancements, not bugs. Many are old (2016-2020) with no recent activity.

## Summary
- **Fixed**: 1 issue (#237)
- **Previously Fixed**: 1 issue (#316)
- **Total Issues Scanned**: 14
- **Actionable Bugs Remaining**: 0 (most open issues are feature requests)
