# Triage Graph: charmbracelet/bubbletea

Repo: charmbracelet/bubbletea (42K stars, Go TUI framework)
Scanned: 2026-05-09
Default branch: main
Status: READY FOR PR

## Summary

**Selected**: Issue #1689 (Kill() data race)
**Fix**: Context cancellation instead of direct shutdown
**Tests**: Pass with `-race`, new test added
**Review**: Codex approved (round 2), Gemini approved
**Branch**: `fix/issue-1689-kill-startup-race` (pushed to fork)
**Drip Queue**: Entry created

## Selected Issue

### #1689 -- Kill() invoked shortly after Run() results in data races
- **Status**: Fix implemented, branch pushed, ready for PR
- **Maintainer signal**: meowgorithm (MEMBER) commented "Makes a ton of sense. Appreciate you flagging this, Liam."
- **Competing PRs**: None
- **Branch**: `fix/issue-1689-kill-startup-race`
- **Fix**: Kill() calls `p.cancel()` instead of `p.shutdown(true)`. Eliminates data races on `handlers`, `cancelReader`, `renderer` by letting Run() handle its own cleanup. Early context check in Run() avoids unnecessary terminal init when Kill() precedes Run().
- **Tests**: `TestKillDuringStartupRace` (from issue reporter's reproduction), passes with `-race -count 20 -cpu 1,4`
- **Review**: Codex (round 1 found panic-recovery deadlock in earlier approach, round 2 approved current approach), Gemini (approved, flagged Wait-before-Run as pre-existing)

## Rejected Candidates

### #1690 -- data race between received mouse events and cursed renderer
- Competing PR: #1691 (open)
- Skip: competing PR already exists

### #1590 -- garbage chars printed on early quit
- Competing PR: #1692 (open, 12 comments on issue)
- Skip: competing PR already exists

### #431 -- ExecProcess writes View output to stdout
- Competing PR: #1687 (open)
- Skip: competing PR already exists

### #1504 -- Tabs example inconsistent spacing
- Competing PR: #1519 (open)
- Skip: competing PR already exists

### #1652 -- textarea infinite loop on alt+left (empty input)
- No competing PR, clear fix path
- Skip: bug is in `charm.land/bubbles/v2` (textarea package), not in bubbletea itself

### #874 -- IME input in wrong position
- Maintainer confirmed: "fixed in v2"
- Skip: already addressed in v2

### #573 -- Altscreen rendering artifacts on resize
- Old issue (2022), maintainer acknowledged but no ETA
- Skip: deep renderer problem, no mechanical fix

### #197 -- Windows-1251 Cyrillic decode error
- Confirmed fixed in v0.26.0
- Skip: should be closed

## Scoring Criteria

| Signal | Weight | #1689 Score |
|--------|--------|-------------|
| Maintainer acknowledged | 3 | Yes (meowgorithm) |
| No competing PR | 2 | Yes |
| Mechanical acceptance criteria | 2 | Yes (race detector passes) |
| Bug (not feature) | 1 | Yes |
| Reproduction provided | 1 | Yes (test in issue) |
| **Total** | | **9/9** |
