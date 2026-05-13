# Triage Graph: charmbracelet/huh

**Repo:** charmbracelet/huh (6,863 stars)  
**Type:** Go form/prompt library  
**Org:** charmbracelet  
**Last updated:** 2026-05-10

## Org-level Context

charmbracelet has an open PR at charmbracelet/lipgloss (#TBD from prior sweep session). Per org-level pacing gates, we're in a warm state with this org. Proceed with caution — one PR at a time per org.

## Scanning Summary

**Total open issues:** 15 (bug/enhancement labeled)  
**Open PRs:** 28  
**Top actionable issues:** 5

## Issue Ranking

### 1. #611 - Accessibility docs not accessible ✅ IMPLEMENTED
- **Type:** documentation bug  
- **Maintainer acknowledgment:** Yes (1 comment from user acknowledging the problem)  
- **Competing PRs:** None  
- **Accessibility impact:** High (directly affects accessibility of accessibility docs)  
- **Fix scope:** Clear — add textual examples  
- **Status:** Fixed on branch `fix-accessibility-docs`

### 2. #630 - Confirm selection insufficiently clear
- **Type:** enhancement (accessibility)  
- **Maintainer acknowledgment:** Medium (2 comments, detailed proposal from user)  
- **Competing PRs:** #685 (similar feature — dynamic marker on confirm)  
- **Accessibility impact:** High (color-blind users cannot distinguish selection)  
- **Fix scope:** Medium — needs visual indicator beyond color  
- **Status:** SKIP — competing PR exists

### 3. #315 - Bubbletea example broken ✅ IMPLEMENTED
- **Type:** bug  
- **Maintainer acknowledgment:** Yes (2 comments, clear repro)  
- **Competing PRs:** None visible  
- **Accessibility impact:** Low  
- **Fix scope:** Medium — keymap conflict resolution  
- **Status:** Fixed on branch `fix-bubbletea-example`
- **Root cause:** Tab/shift-tab were bound to both Toggle and Next/Prev in ConfirmKeyMap, causing Toggle to take precedence
- **Solution:** Removed tab/shift-tab from Toggle binding, kept only arrow keys for toggling

### 4. #468 - Note skip behavior undocumented/broken
- **Type:** bug + docs  
- **Maintainer acknowledgment:** Low (0 comments)  
- **Competing PRs:** None  
- **Accessibility impact:** Low  
- **Fix scope:** Medium-complex — form.go logic interacts with field_note.go WithPosition  
- **Status:** SKIP — complex edge cases, zero maintainer engagement
- **Investigation notes:**
  - Skip example exists at examples/skip/ but doesn't demonstrate single-note groups
  - Root cause: form.go has `group.selector.Total() == 1` check that prevents skip
  - But field_note.go WithPosition also sets `n.skip = false` for single-field groups
  - Unclear if this is intentional design or bug — needs maintainer clarification

### 5. #286 - Windows Tab/Enter keys not handled correctly
- **Type:** bug (Windows-specific)  
- **Maintainer acknowledgment:** High (4 comments, maintainer said "should be fixed on main" but user reports still broken)  
- **Competing PRs:** None  
- **Accessibility impact:** Medium (blocks Windows users)  
- **Fix scope:** Medium — platform-specific key handling  
- **Status:** CANDIDATE for next iteration (needs verification of current state)

## Denied Issues

None yet.

## Hypothesis Evidence

**H0 (Bug fixes merge, features don't):** #611 is a docs bug, should have high merge probability.  
**H1 (Accessibility PRs favored):** huh has first-class accessibility mode — accessibility fixes align with maintainer values.  
**H2 (Org-level pacing matters):** charmbracelet already has open PR at lipgloss. This is evidence for H2.  
**H4 (Competing PRs reduce merge probability):** #630 has competing PR #685, so we skipped it.

## Implementation Summary

**Completed:** 2/5 top issues
- #611: Accessibility docs (README examples for screen readers) — branch `fix-accessibility-docs`
- #315: Confirm field navigation bug (keymap conflict) — branch `fix-bubbletea-example`

**Skipped:** 3/5
- #630: Competing PR #685 exists
- #468: Complex edge cases + zero maintainer engagement
- #286: Windows-specific, needs device testing (not feasible in pipeline)

## Next Steps

1. Drip push #611 and #315 when lipgloss PR closes or after 2-week cooldown
2. If both merge: consider #468 or #286
3. Monitor for new high-value issues
