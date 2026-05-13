# Triage Graph: Sekai-World/sekai-viewer

**Repo**: Sekai-World/sekai-viewer (499★, TypeScript)  
**Description**: Web Database Viewer of Project Sekai  
**Triage Date**: 2026-05-11  
**Open Issues**: 21

## Issues Triaged

### #624: Skill level validation bug ✅
- **Type**: Bug
- **Root cause**: `scoreCalc.ts` directly indexes `skillEffectDetails` array without bounds checking
- **Fix**: Clamp skillLevel to valid range (1 to maxSkillLevel) before array access
- **Files**: `src/utils/scoreCalc.ts`
- **Branch**: `fix/skill-level-validation`
- **Evidence**: User reported TypeError when skill level > 4; UI has max=4 input hint but no enforcement

### #623: Card story voice 404 errors ✅
- **Type**: Bug (data handling)
- **Root cause**: JSON scenario IDs contain " のコピー" (copy) suffix, causing asset path mismatches
- **Fix**: Strip suffix in `scenarioIdToAssetbundleName` function
- **Files**: `src/utils/storyLoader.ts`
- **Branch**: `fix/card-story-voice-link`
- **Evidence**: Issue shows exact 404 URL with "%20%E3%81%AE%E3%82%B3%E3%83%94%E3%83%BC" (URL-encoded copy suffix)

### #591: Event PT Calculator NaN for World Bloom events ✅
- **Type**: Bug (missing case)
- **Root cause**: `getEventPoint` switch statement lacks `world_bloom` case, returns undefined
- **Fix**: Add `world_bloom` to marathon case (same calculation formula)
- **Files**: `src/utils/scoreCalc.ts`
- **Branch**: `fix/world-link-event-calc`
- **Evidence**: EventType includes "world_bloom" but scoreCalc only handles marathon/carnival/challenge

### #671: Stamp page search functionality ✅
- **Type**: Feature
- **Implementation**: TextField filter on stamp name and description (case-insensitive)
- **Files**: `src/pages/stamp/StampList.tsx`
- **Branch**: `feature/stamp-search`
- **Integration**: Added to existing filter panel alongside character and type filters

### #677: Enable new tab navigation ⏸️
- **Type**: Feature (UX enhancement)
- **Scope**: Replace onClick navigation with proper link elements for middle-click/new-tab support
- **Complexity**: Requires architectural change across multiple list views
- **Status**: Deferred - vague scope, needs maintainer input on desired navigation patterns

## Patterns Observed

1. **Missing input validation**: #624 shows TypeScript doesn't prevent runtime array bounds errors
2. **Data quality issues**: #623 indicates upstream data contains file system artifacts
3. **Incomplete event type handling**: #591 shows new event types need explicit switch cases
4. **Good feature request format**: #671 had clear motivation and suggested implementation

## Denylist

None established. All attempted fixes were valid and isolated.

## Recommendations

- Add input validation layer for user-editable numeric fields
- Consider defensive coding for array access in calculation utilities
- Test suite would catch issues like #624 and #591 before users encounter them
- Event type enum should have exhaustive switch coverage or default case

## Statistics

- Issues triaged: 5
- Fixes implemented: 4
- Features added: 1
- Average complexity: Low (isolated single-file changes)
- Maintainer responsiveness: Mixed (some issues have 6+ month age with contributor discussion)
