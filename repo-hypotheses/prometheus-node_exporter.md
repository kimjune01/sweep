# Triage Graph: prometheus/node_exporter

**Date:** 2026-05-09
**Repo:** https://github.com/prometheus/node_exporter
**Category:** Prometheus ecosystem, Go, 13K stars

## Repo Health

- Active maintainers: SuperQ (MEMBER), discordianfish (MEMBER)
- Good-first-issue count: 3 open
- Adjacent to: prometheus/client_golang (already in roster), prometheus/procfs (dependency)
- Merge cadence: dependabot + community PRs merge regularly

## Issues Scanned

### #2980 -- Handle thermal_zone errors gracefully [SELECTED]
- **Labels:** enhancement, accepted, good first issue
- **Competing PRs:** None on node_exporter side
- **Upstream dependency:** prometheus/procfs#794 (merged 2026-03-15) -- refactored `ClassThermalZoneStats` to surface per-zone `ReadErrors` instead of silently skipping or failing the entire collector
- **Maintainer engagement:** High -- SuperQ filed procfs#794 himself, commented in issue with clear direction
- **Acceptance criteria:** Disabled/unreadable thermal zones logged as debug, healthy zones still report metrics. Entire collector no longer fails when one zone is unreadable.
- **Effort:** Small (1 collector file + procfs bump)
- **Branch:** `fix/thermal-zone-error-handling`
- **Implementation:** Bumped procfs to commit 465fd94215fd (includes PR#794 `ReadErrors` field). Node_exporter now checks `stats.ReadErrors` per zone -- logs at debug level and skips zones with errors. Healthy zones continue reporting. Top-level error handling preserved for sysfs-not-found cases.
- **Status:** Committed, tests pass (go test ./... -- all ok)
- **Risk:** Depends on unreleased procfs (pseudo-version). Maintainer may prefer waiting for a tagged release. If so, PR can sit until procfs tags v0.21.0.

### #2097 -- Add label for mount point to mountstats [SKIP]
- **Labels:** accepted, help wanted, good first issue
- **Competing PRs:** #3554 (Feb 2026, actively being reworked by Vedant-Mhatre per SuperQ's direction toward `node_mountstats_nfs_mountpoint_info`), #2676 (2023, stale)
- **Maintainer engagement:** High -- SuperQ gave specific architectural guidance (March 2026)
- **Assessment:** Contested. Vedant-Mhatre is actively working on it with maintainer alignment. Design direction still evolving (info metric vs label). Not a good target.

### #2336 -- Replace netstat parsers with procfs netstat parsers [SKIP]
- **Labels:** enhancement, accepted, good first issue
- **Competing PRs:** #2360 (2022, WIP, stale), #3621 (Apr 2026, closed)
- **Assignee:** nikakis (inactive, explicitly handed off)
- **Assessment:** Multiple failed attempts over 4 years. Requires changes in both procfs and node_exporter. PR #3621 was recently closed (Apr 2026). Complex refactor with `*float64` type changes in procfs. Not a first-PR target despite the label.
