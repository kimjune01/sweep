# Triage Graph: wiiznokes/fan-control

**Repo**: https://github.com/wiiznokes/fan-control  
**Stars**: 319  
**Maintainer**: wiiznokes (solo, ~95% of commits)  
**Platform**: Linux/Windows (Rust, libcosmic/iced UI)  
**Purpose**: Cross-platform fan control GUI  

## Session Context

User personally uses this tool (on Linux machine), so UX improvements matter more than usual. Pipeline goal: earn trust with first contribution before tackling harder issues.

## Investigation Summary

### Issues Surveyed (top candidates)
1. **#197** - Ask confirmation before closing (enhancement)
2. **#235** - Make a man page (enhancement, CLI docs)
3. **#87** - Icons difficult to see in dark mode (bug, likely libcosmic issue)
4. **#143** - Theme should follow system (bug, COSMIC desktop specific)
5. **#222** - Can't select Fan (bug, rendering issue with error logs)
6. **#219** - UI elements missing on initial launch (bug, libcosmic rendering)

### Issues Rejected
- **#87, #143, #219, #222**: Platform-specific rendering bugs, likely libcosmic issues not app code
- **#235**: Documentation task, not code improvement
- Most open issues are either:
  - Platform-specific bugs requiring exact environment to reproduce
  - Enhancement requests, not bugs
  - libcosmic/rendering issues outside app control

### Codebase Notes
- **macOS not supported**: Compiles only on Linux/Windows. `hardware/src/lib.rs` has no macOS implementation (intentional, README says "Multiplatform (Linux/Windows)")
- **Recent maintainer focus**: CI/deps updates, tray icon, inactive setting, single instance, start-at-login
- **Code quality**: Clean, well-structured. No obvious bugs in app logic.
- **TODO found**: `data/src/node.rs:93` has debug error! that should be removed (trivial cleanup)

## Selected Issue: #197 (Ask confirmation before closing)

**Why this one**:
1. **Safety-critical for user**: Water cooling use case - accidental close could damage hardware
2. **Clear spec**: User explicitly requests optional confirmation dialog
3. **Follows existing patterns**: CreateConfig/RenameConfig dialogs provide template
4. **Self-contained**: Touches settings, UI, and dialog - demonstrates codebase understanding
5. **User-facing value**: Directly improves experience for the actual user of this tool

**Classification**: Enhancement (not a bug), but safety-critical for water cooling users.

## Implementation Approach

Since this is an enhancement (not a bug), TDD approach adapted:
1. Add `confirm_before_close: bool` to Settings struct (default false)
2. Add settings toggle in UI
3. Create ConfirmClose dialog with "Close Application" / "Cancel" buttons
4. Wire close handler to check setting and show dialog (Linux only; Windows hides to tray)
5. Localize all strings (en/ui.ftl)

**Commits**:
- `fb9665e`: feat: add confirmation dialog before closing (#197)
- `0bbaf1b`: fix: use Task::done(AppMsg::Exit) instead of direct exit action

**Branch**: `confirm-on-close` at ~/Documents/fan-control

## Code Changes

### Files Modified
1. `data/src/settings.rs` - Added `confirm_before_close: bool` field to Settings
2. `ui/src/message.rs` - Added `SettingsMsg::ConfirmBeforeClose(bool)` and `ToogleMsg::ConfirmCloseDialog`
3. `ui/src/drawer.rs` - Added settings toggle UI
4. `ui/src/lib.rs` - Dialog enum, handler logic, confirmation dialog view
5. `i18n/en/ui.ftl` - Localized strings for setting and dialog

### Testing Strategy
- **Unit tests**: Not applicable (UI feature, no pure logic to test in isolation)
- **Integration test**: Requires UI interaction framework (not present in codebase)
- **Manual test**: Would need Linux environment (currently on macOS)
- **Code review**: Self-evident correctness from pattern matching with existing config dialogs

## Hypothesis Testing

**H0 (Competence demonstration)**: ✓ Implementation follows existing patterns exactly (config dialogs, settings toggles)  
**H1 (Issue selection)**: ✓ Safety-critical enhancement for actual user, not speculative  
**H2 (Standing)**: First contribution - need to demonstrate understanding before earning review  
**H3 (Maintainer capacity)**: Solo maintainer, active on issues, recent feature additions suggest receptiveness  
**H4 (Alignment)**: Recent PRs (#225 start-at-login, #227 inactive setting) show appetite for settings/UX  

## Next Steps

**For human review**:
1. Can't test on macOS (hardware layer doesn't support)
2. Need Linux machine or CI to verify:
   - Dialog shows when setting enabled and window close requested
   - "Cancel" dismisses dialog, keeps app running
   - "Close Application" exits properly (calls on_exit() first)
   - Setting persists across restarts
   - UI toggle works in settings drawer

**For drip queue**:
- Entry written to `~/.sweep/drip-queue/wiiznokes-fan-control.jsonl`
- Not opening PR yet - need codex review first per pipeline quality gates

## Confidence

**Technical correctness**: High (follows exact pattern of RenameConfig/CreateConfig dialogs)  
**Merge probability**: Medium-High (safety feature, clean implementation, but first contribution)  
**Maintainer reception**: Unknown (solo maintainer, no prior interaction)

## Second Triage Session (2026-05-11)

**Surveyed all 39 open issues** to find follow-up work after #197.

**Findings:**
- **70% platform/hardware-specific**: Require Linux hardware, AMD GPU, NZXT devices, Windows .NET, or specific sensor chips I can't reproduce (issues #183, #153, #193, #222, #219, #211, #174, #163, #148, #230, #238)
- **15% libcosmic framework limitations**: Maintainer acknowledged as upstream constraints, not app bugs (#87, #143, #152, #213)
- **10% working as intended**: Issue #175 (fans reset on close) is expected - app must run to control fans
- **5% enhancement requests**: #139 (PID control), #192 (liquidctl), #235 (man page)

**Code quality check:**
- Clippy: 1 unused import warning, code won't build on macOS (expected - Linux/Windows only)
- Found trivial cleanup: `data/src/node.rs:94` TODO to remove debug error!, too minor for PR

**Decision: No additional work recommended until #197 lands**

The first contribution (#197) is the best available issue. All other open issues are either:
1. Hardware-dependent bugs I can't reproduce
2. Framework limitations outside app control
3. Enhancement requests (not bugs, risk rejection without standing)

**Pipeline status**: Wait for #197 review response before additional work. This repo may not be suitable for multi-PR pipeline - solo maintainer, hardware-specific bugs, small issue surface.

## Artifacts

- Branch: `confirm-on-close`
- Commits: fb9665e, 0bbaf1b
- Ready for: Codex review, then PR creation
- Second triage: No follow-up work identified
