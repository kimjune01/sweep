# VictoriaMetrics/VictoriaMetrics Triage Graph

Date: 2026-05-09
Repo: VictoriaMetrics/VictoriaMetrics (17K stars, Go, Prometheus-compatible monitoring)
External merge rate: 39%

## Repo Profile

- Maintainers: makasim (Max Kotliar), f41gh7 (Nikolay), Haleygo (Hui Wang), AndrewChubatiuk
- Review style: changes-requested with inline comments, detailed
- CI bot: cubic-dev-ai (automated code review)
- Label discipline: good (good-first-issue, help-wanted, component labels)
- Competing PR density: HIGH — all 4 good-first-issues have open PRs

## Good-First-Issue Scan (4 open)

| Issue | Title | Competing PR | Status |
|-------|-------|-------------|--------|
| #8856 | vmagent: limit parse error logs | PR #10015 (meroupatate) | OPEN, changes-requested since Jan 2026, stale 3mo |
| #9651 | Offset in instant queries | PR #10810 (SamarthBagga) | OPEN, under review |
| #9450 | Rollup memory limit | PR #10293 (OrlovEvgeny) | OPEN, under review |
| #5914 | vmctl: InfluxDB v2 migration | PR #6830 (closed) | CLOSED, 88K additions, abandoned |

## Help-Wanted Scan (10 open)

| Issue | Title | Competing PR | Picked? |
|-------|-------|-------------|---------|
| #9436 | Introduce usernameFile for Basic Auth | NONE | **YES** |
| #10091 | IONOS service discovery | NONE | No — large scope, new SD |
| #9758 | Cosign OCI signing | NONE | No — CI/release pipeline, not code |
| #9975 | Better flag search in docs | NONE | No — docs-only, low signal |
| #9976 | API/field/structure reference | NONE | No — docs-only |
| #10927 | vmauth JWT templating | PR #10930 (contested, 1 day old) | No |
| #9989 | Unix socket for vmauth | PR #10331 (contested) | No |
| #9663 | Single underscore labels | PR #10475 (contested) | No |
| #8747 | Config divergence metric | PR #10591 (contested) | No |

## Selected: Issue #9436

**Why this issue:**
1. Filed by maintainer f41gh7 — signals internal priority
2. Clear mechanical spec: "add usernameFile like passwordFile"
3. Uncontested — zero competing PRs
4. Security-labeled — high-trust category
5. lib/promauth already supports username_file in YAML; gap is CLI flags only
6. Small, focused change (37 additions, 9 deletions, 12 files)

**Implementation:**
- Added `basicAuth.usernameFile` CLI flags to 5 locations:
  - `app/vmagent/remotewrite/client.go` (ArrayString flag)
  - `app/vmalert/datasource/init.go` (String flag)
  - `app/vmalert/remotewrite/init.go` (String flag)
  - `app/vmalert/remoteread/init.go` (String flag)
  - `app/vmalert/notifier/init.go` (ArrayString flag)
- Updated `app/vmalert/vmalertutil/auth.go` WithBasicAuth to accept usernameFile param
- Updated `app/vmalert/notifier/alertmanager.go` to pass UsernameFile
- Updated flag docs (vmagent_common_flags.md, vmalert_common_flags.md, vmgateway.md)
- Added CHANGELOG entry under ## tip
- Updated test files for new function signature

**Branch:** `feat/basic-auth-username-file`
**Tests:** All pass (`go test ./lib/promauth/... ./app/vmalert/... ./app/vmagent/remotewrite/...`)

## Next Actions

- Push branch and open PR via /drip
- If merged: #5914 (InfluxDB v2 migration) is uncontested but large scope — potential follow-up after trust established
- #8856 has a stale competing PR (3 months, changes-requested) — could supersede if PR author abandons
