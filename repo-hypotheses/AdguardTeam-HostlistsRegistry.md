# AdguardTeam/HostlistsRegistry Triage Graph

**Repo type**: Content registry + build tooling (JavaScript)
**Stars**: 366
**Open issues**: 39
**Maintainer pattern**: Accepts PRs, but focus is on blocklist curation

## Scan Summary (2026-05-11)

Scanned all 39 open issues. Classification:

### Blocklist Inclusion Requests (26 issues)
These require maintainer judgment on filter quality, not code contributions:
- #820 (Hagezi Multi-Lite)
- #799 (botnet-filter)
- #794 (ThreatFox)
- #770 (OISD NSFW)
- #753 (Government Malicious Site List)
- #719 (Hagezi NRD/DGA)
- #708 (OISD NSFW duplicate)
- #695 (Hagezi TIF IPs)
- #694 (ShadowWhisperer Typo)
- #668 (Cryptocurrency Phishing)
- #666 (SemperVideo RPiList)
- #654 (BadBlock lists)
- #649 (Hagezi referral - IN PROGRESS)
- #645 (Scam list)
- #583 (Social Media Blocklist)
- #561 (AI Blocklist)
- #549 (hBlock - controversial, rejected before)
- #240 (Firebog green entries)

**GATE_FAIL**: Cannot contribute code to these - they're policy decisions.

### False Positive / Filter Issues (5 issues)
These need to be reported to upstream filter maintainers:
- #819 (chess.com blocked by CHN: anti-AD `||analysis*.*^` rule)
- #813 (Spotify video blocking stopped - config drift, user provided workaround)
- #746 (False Positive - vague, no details)

**GATE_FAIL**: Not code bugs in this repo. #819 needs upstream filter fix.

### Service/Feature Requests (4 issues)
- #802 (PlayStation telemetry domains) - data contribution, not code
- #801 (Chinese language feature request)
- #775 (LG Channels service) - needs testing + data
- #707 (Hagezi DNS Servers Only list) - blocklist request

**GATE_FAIL**: Data contributions or require device testing.

### Infrastructure / Code Quality (4 issues)
- **#422** (Add locales validate script) - infrastructure
- **#421** (Improve locales scripts - node vs bash) - refactor
- **#382** (Add semantic groups to services.json) - enhancement, already partially done
- **#374** (Use yml filename as id source) - refactor
- **#360** (Add tests for services scripts) - testing infrastructure

**ASSESSMENT**: These are valid code improvements but require:
1. Understanding AdGuard's internal tooling conventions
2. Large refactors (not small bugs)
3. No mechanical acceptance criteria

### Security (1 PR, not issue)
- **PR #807** (Path traversal fix) - ALREADY OPEN
  - Fixes `scripts/services/restore-removed-services.js:L26`
  - Validates `removedObject.id` against path traversal

## Hypothesis Evidence

### H0 (Clear mechanical acceptance): ❌ CONTRA
- No issues with "fails on main, passes after fix" pattern
- All issues require judgment calls or are blocklist/data contributions

### H1 (Maintainer-acknowledged): ✅ NEUTRAL
- Issues stay open, maintainers respond (e.g., #775 has maintainer questions)
- But responses are sparse - not actively triaging

### H2 (Solo maintainer, small fixes): ⚠️ WEAK CONTRA
- Repo has 366 stars, multiple contributors
- But most issues are about filter curation, not code

### H3 (200-500 star sweet spot): ✅ SUPPORTS
- 366 stars fits the bucket
- But content registry pattern doesn't match typical code repo

### H6 (AI-friendly policy creates flood): ✅ SUPPORTS
- 39 open issues, many are duplicates or similar requests
- Multiple hBlock requests (#549, #506, #442) all rejected
- Multiple OISD NSFW requests (#770, #708)

## Actionable Findings

**KILLED (0 issues)**:
- None yet

**REJECTED (39 issues)**:
- All issues fail actionability gate:
  - 26 blocklist inclusion requests (policy, not code)
  - 5 false positives (upstream filter issue)
  - 4 service/data requests (no code fix)
  - 4 infrastructure (large refactors, no clear acceptance)

**GATE_FAIL REASONS**:
1. **Policy decisions**: Blocklist inclusion requires maintainer judgment on source quality
2. **Upstream issues**: False positives need filter maintainer fixes, not registry fixes
3. **Data contributions**: Service additions are YAML data, not code bugs
4. **Refactor scope**: Infrastructure improvements lack mechanical acceptance criteria

## Recommendation

**DO NOT PROCEED** with this repository for the pipeline.

**Reasons**:
1. This is a **content registry**, not a code repository
2. Issues are **curation decisions**, not bugs
3. The one security issue (path traversal) **already has PR #807**
4. No issues match the TDD pattern (write failing test → fix → test passes)

**Alternative approach**:
- If AdGuard accepts filter contributions: contribute to individual filter repos
- If interested in build tooling: tackle #360 (add tests) as standalone improvement
- But neither fits the "sweep→triage→investigate→fix" pipeline model

**Pipeline status**: EVICTED (wrong repo type)
