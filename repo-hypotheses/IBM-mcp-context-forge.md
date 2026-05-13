# Triage Graph: IBM/mcp-context-forge
Date: 2026-05-09

## Pipeline Outcome
**Status**: SUCCESS - 1 PR queued

## Selected Issue
**Issue #4644**: OTEL_EXPORTER_OTLP_INSECURE configuration setting is defined but not used

### Why This Issue
- **Bug, not feature**: Configuration setting exists but doesn't work
- **Clear acceptance criteria**: Pass `insecure` parameter to OTLP exporters
- **No competing PRs**: Issues #4662, #4667 had multiple competing PRs
- **Maintainer-acknowledged**: Has `triage` label, clear bug classification
- **Real user impact**: Documented workaround exists, users hitting SSL errors with self-signed certs

### Fix Approach
1. Pass `cfg.otel_exporter_otlp_insecure` to both GRPC and HTTP OTLP exporter constructors
2. Remove outdated comment about exporter compatibility (OpenTelemetry 1.41.0+ is required)
3. Add unit tests for both GRPC and HTTP protocol paths

### Branch
`fix/otel-insecure-setting-4644`

Commit: bffce28b1

## Issues Scanned (30 total)

### Actionable Issues
1. **#4644** - OTEL_EXPORTER_OTLP_INSECURE not used (SELECTED)
2. **#4645** - DB_POOL_SIZE per-worker calculation bug
3. **#4670** - User dict passed instead of email string
4. **#4671** - API Token Scope Enforcement not working
5. **#4630** - Redis maxclients limit exceeded

### Issues with Competing PRs (skipped)
- **#4662** - LLM provider/model forms broken (2 open PRs: #4663, #4620)
- **#4667** - Vault plugin header case-sensitivity (2 draft PRs: #4668, #4666)

### Feature Requests (skipped per "bug fixes only" rule)
- #4687, #4686, #4685, #4680 - All enhancement/feature requests
- #4681, #4682, #4684, #4689, #4688, #4665 - Chores/enhancements

### Infrastructure/Docs/Design (not actionable)
- #4648 - CI workflow enhancement
- #4643, #4642, #4631 - UI-rewrite tasks
- #4632 - Enterprise demo request
- #4655, #4653 - Security hardening (CSP/Alpine.js)

### Rust Dataplane (out of scope)
- #4664, #4652, #4651, #4649, #4647 - Tagged CF-DATAPLANE

## Trust Context
- **Org**: IBM
- **Prior merges**: 3 PRs at IBM/mcp-cli (same org)
- **Relationship**: Warm lead - established contributor

## Competing PR Analysis
- Issue #4644: 0 competing PRs
- Issue #4662: 2 competing PRs (sealkrach, meltforce)
- Issue #4667: 2 draft PRs (fix/vault-plugin-header-case-sensitivity, popagruia)

## Notes
- Repository is very active: 30 open issues scanned, 10 created in past 24 hours
- Strong labeling system: triage, bug, enhancement, chore, security, ui-rewrite
- Multiple active feature branches: ui-rewrite, CF-DATAPLANE
- Good test coverage: unit tests in tests/unit/mcpgateway/
