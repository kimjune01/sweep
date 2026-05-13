# Triage Graph: StevenWeathers/thunderdome-planning-poker

**Repo**: StevenWeathers/thunderdome-planning-poker  
**Stars**: 490  
**Language**: Go (backend), Svelte/TypeScript (frontend)  
**Description**: Agile planning poker, sprint retrospectives, story mapping tool  
**Triage Date**: 2026-05-11

## Hypothesis Classification

**H6 (Maintainer-Driven)** - Not actionable for autonomous contributions.

## Evidence

### Contribution Pattern
- **Recent merged PRs (last 50)**: 48 from maintainer (StevenWeathers), 1 from dependabot, 1 from external (DominikHerold #830 - 1-line bug fix)
- **Recent activity**: 10 PRs merged May 9-10, 2026 - maintainer is highly active
- **External contributor pattern**: Extremely rare, very small scope (< 10 LOC), bug fixes only

### Project Philosophy
- **"AI-FREE by Design"** - README states: "Thunderdome is intentionally built without any AI driven features. We believe authentic human collaboration is essential for meaningful team decision-making and agile planning. Therefore, we will not be accepting any issue requests or pull requests for AI driven features."
- Contributing guide allows AI tools but with strong caveats: "Do not use AI to 'vibe code' entire features without careful understanding"

### Issue Landscape (26 open issues)
Examined top issues:
- **#886-884**: Feature requests (Team timezone, Retro UX, Team roles) - large scope
- **#821**: Feature request (Close empty groups) - requires UI/UX design, maintainer commented on trade-offs
- **#762**: Feature request (Bell sound on vote finish) - requires sound API integration, user settings persistence
- **#644**: Bug (API inconsistency) - maintainer already addressed in comments, won't fix without breaking API, acknowledged validation messages need improvement but no action plan
- **#738**: Feature request (Point scales in storyboards) - maintainer just updated May 10 linking to recent work
- **#693-552**: Large feature requests (i18n library replacement, SSO, Jira integration, etc.)

### Code Quality
- All tests pass (`go test ./internal/...` - 100% pass rate)
- No obvious TODO/FIXME that are actionable (middleware_test.go has empty test stubs but that's intentional scaffolding)
- Linter requires build setup (UI dist/ must exist)

### Repository Characteristics
- **Branch policy**: Fork, branch from `main`, add tests (standard GitHub Flow)
- **CLA**: None mentioned
- **No CONTRIBUTING policy violations**: Standard contribution guide
- **Test coverage**: Unit tests exist, E2E with Playwright

## Decision

**NO PRs CREATED**

### Rationale
1. **Maintainer velocity**: Maintainer is shipping 5+ PRs/week, actively developing features
2. **External contribution friction**: Only 2 external PRs in last 50 merged, both < 10 LOC
3. **Issue complexity**: All open issues are feature requests requiring architectural decisions or UX design
4. **Philosophy alignment**: "AI-FREE by Design" suggests maintainer has strong opinions on authentic human collaboration
5. **No low-hanging fruit**: No failing tests, no obvious bugs, no documentation gaps that aren't already being addressed

### Pipeline Recommendation
**SKIP** - This is a well-maintained, maintainer-driven project. Autonomous PR creation would likely be unwelcome. Better suited for:
- Watching for future bug reports from users
- Contributing only after establishing relationship through issue discussions
- Waiting for maintainer to explicitly tag issues as "good first issue" or "help wanted"

## Competing PRs

None found (no external PRs in recent history).

## Tags

#h6-maintainer-driven #ai-free-philosophy #high-maintainer-velocity #feature-heavy-backlog
