# Triage Graph: boldsoftware/shelley

**Repository**: boldsoftware/shelley (464★, Go)  
**Triage Date**: 2026-05-11  
**Open Issues**: 90

## Selection Criteria

Prioritized smallest/easiest issues for standing:
- Documentation gaps
- UI polish
- Small bug fixes
- Edge cases

Avoided:
- Already-fixed issues (91, 192, 198 fixed but still open on GitHub)
- Feature requests requiring architecture changes
- Issues requiring deep domain knowledge

## Issues Investigated

### #207: Document the ! command for searching conversation history
**Status**: ✅ Fixed  
**Branch**: fix-207-document-bang-command  
**Commit**: 87c006a  

**Problem**: The `!` command for SQLite queries exists in the system prompt and skills, but not in user-facing documentation.

**Solution**: Added "Using Shelley" section to README.md with three common search patterns:
- List recent conversations
- Get messages from specific conversation  
- Search conversations by keyword

**Hypothesis**: H2 (good-first-issue receptiveness) - documentation improvements show attention to user needs, low controversy.

---

### #147: Update default GLM version in model picker to GLM 5
**Status**: ✅ Fixed  
**Branch**: fix-147-update-glm-default  
**Commit**: f6e6d96  

**Problem**: GLM-4.7 appeared before GLM-5.1 in the model picker, making the older version more prominent.

**Solution**: Reordered models in `models/models.go` to show GLM-5.1 before GLM-4.7 and DeepSeek.

**Hypothesis**: H0 (baseline) - straightforward preference update, no complexity.

---

### #136: Support empty authorization string in BYOK model dialog
**Status**: ✅ Fixed  
**Branch**: fix-136-empty-auth-string  
**Commit**: 69e0c00  

**Problem**: Some providers don't require API keys, but Shelley rejected empty authorization strings.

**Solution**: Updated `ModelsModal.tsx` validation:
- Removed API key requirement from test/save validation
- Updated button disabled states
- Simplified error messages

**Hypothesis**: H0 (baseline) - bug fix for edge case, enables legitimate use case.

---

## Already Fixed (Still Open on GitHub)

### #91: Sort archived conversations by latest message timestamp
**Fixed in**: 3881131  
Removed `updated_at = CURRENT_TIMESTAMP` from ArchiveConversation query.

### #192: Fix LLM response parsing: summary field should be object
**Fixed in**: 2e4b66c  
Changed `Summary string` to `Summary []responsesSummary` in oai_responses.go.

### #198: VM menu shows outdated link after name change
**Fixed in**: dd54a29  
Auto-derive terminal_url from current hostname on /exe.dev VMs.

## Denylist

None - first triage run for this repo.

## Evidence

- **Repo maturity**: 464★, active development, professional team
- **Issue quality**: Discord-sourced, includes reproduction steps and maintainer comments
- **Review culture**: Fast feedback on PRs (seen in git log)
- **Standing strategy**: Start with docs + small fixes to establish trust

## Next Steps

All three fixes queued for drip. Ready for quality gates before push.
