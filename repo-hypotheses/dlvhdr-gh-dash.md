# dlvhdr/gh-dash Triage Graph

**Repo**: dlvhdr/gh-dash (11.5K stars)
**Stack**: Go, Bubble Tea TUI
**Maintainer**: dlvhdr (solo, merges external PRs regularly)
**Triage date**: 2026-05-09

## Repo Health

- Active: last commit within days, PRs merged regularly
- 11 open PRs, mix of small fixes and large features
- Solo maintainer with consistent review cadence
- Labels: bug, feat, good first issue, low-pri, mid-pri

## Selected Issue

### #596 - Default option for close/reopen PR/issue should be "no" (safer)
- **Labels**: feat, mid-pri
- **Maintainer signal**: dlvhdr commented "Agree" (2025-10-04)
- **Competing PRs**: None
- **Complexity**: Low -- change prompt text and input handling in 6 files
- **Risk**: Low -- no API changes, purely defensive UX
- **Branch**: `fix/default-confirmation-to-no`
- **Commit**: b145b00

### Changes Made
1. All confirmation prompts changed from `(Y/n)` to `(y/N)` in `section/section.go`
2. Removed `input == ""` from accept condition in 4 section files (prssection, issuessection, reposection, notificationssection) so Enter alone no longer confirms
3. Fixed inconsistency in `notificationview.go` where prompts already showed `(y/N)` but Enter still confirmed
4. Updated all affected tests (prssection_test.go, notificationview_test.go, ui_test.go)

## Candidates Evaluated

### #689 - Ability to create PRs and Issues
- **Labels**: feat, good first issue, mid-pri
- **Status**: hawkaii claimed it (2026-03-07), maintainer engaged. Workaround exists via custom keybindings.
- **Decision**: Skip -- claimed, large scope, maintainer has full design mockup planned

### #578 - Crash in help menu
- **Labels**: bug, mid-pri
- **Status**: Panic on scroll in help menu at small terminal sizes. Upstream bubbles viewport issue.
- **Decision**: Viable but likely requires bubbles dependency fix or workaround. Higher risk.

### #815 - Add shortcut to copy branch name
- **Labels**: none
- **Status**: No maintainer signal, no labels. Feature request.
- **Decision**: Skip -- no maintainer acknowledgment, feature not bug

### #805 - Auto-merge keybinding
- **Labels**: none
- **Status**: Detailed feature request with workaround. No maintainer response.
- **Decision**: Skip -- large scope, no maintainer signal

### #583 - Delete branch when closing PR
- **Labels**: feat, low-pri
- **Status**: Low priority, no maintainer comment.
- **Decision**: Skip -- low-pri, no signal

## Open PRs (competing work check)
- PR #861 - browser launcher fix (#829)
- PR #860 - Windows custom commands (#686)
- PR #849 - PR update branch state
- PR #809 - GraphQL merge + auto-merge indicators
- PR #794 - worktree checkout support (#544)
- PR #786 - OSC52 clipboard
- PR #749 - multi-host support
- PR #723 - theming system
- PR #722 - mouse support

None compete with #596.
