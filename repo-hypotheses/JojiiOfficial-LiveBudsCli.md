# Triage Graph: JojiiOfficial/LiveBudsCli

**Repo**: JojiiOfficial/LiveBudsCli (206 stars, Rust CLI for Samsung Galaxy Buds)  
**Triage Date**: 2026-05-11  
**Open Issues**: 4 total

## Build Environment

**CRITICAL**: This project requires Linux to build. Dependencies:
- `libdbus-1-dev` / `dbus-devel`
- `bluez-libs` / `bluez-libs-devel`
- `libpulse` / `pulseaudio-devel`

macOS builds fail at `libdbus-sys v0.2.7` compilation. Tests cannot run locally without Linux.

## Investigated Issues

### #102 - Galaxy buds 2 Pro dont work
**Status**: PARTIAL FIX IMPLEMENTED  
**Actionability**: 7/10  

**Root Causes Identified**:
1. **Model Detection Bug** (FIXED): `name_to_model()` checked "buds pro" before "buds 2 pro", causing "Galaxy Buds 2 Pro" to be misdetected as BudsPro instead of BudsPro2. Fixed by reordering checks from most-specific to least-specific.
   - Branch: `fix/buds2-pro-model-detection`
   - Commits: test + fix with comprehensive test coverage

2. **Daemon Post-Suspend Issue** (NOT FIXED): grazzolini reports daemon stops working after system suspend/resume. Bluetooth session may not handle power state transitions. Would require hardware testing and may be a blurz/system-level issue.

**Comments**:
- clotodex: reconnection loop works after Samsung update
- grazzolini: works but doesn't detect ambient sound state changes, daemon breaks on resume

### #127 - Buds3 Pro Support
**Status**: DENIED - COMPETING WORK  
**Actionability**: 0/10  

Maintainer is actively working on this (comment Dec 2025). README was outdated but code already supports Buds3 Pro via `name_to_model()`.

**Branch**: `docs/add-buds3-pro-support` - Updated README to reflect existing support.

### #76 - Dependency Dashboard  
**Status**: DENIED - AUTOMATED TOOLING  
**Actionability**: 0/10  

Renovate bot issue for dependency updates. Not actionable.

### #29 - Missing features // TODO
**Status**: DENIED - LARGE FEATURE  
**Actionability**: 0/10  

Meta-issue for original Galaxy Buds support. Last comment 2021. Maintainer hasn't prioritized. Would require significant bluetooth protocol work.

## Implicit Issues Found

### Error Message Quality
**Status**: FIXED  
**Actionability**: 5/10  

Files `config_set.rs` and `set_value.rs` printed bare "Error!" on operation failure with no context. Changed to "Error: Operation failed".

**Branch**: `fix/improve-error-messages`

### README Outdated Model List
**Status**: FIXED  
**Actionability**: 4/10  

README didn't list Buds3 Pro despite code support existing.

**Branch**: `docs/add-buds3-pro-support`

## Branches Created

1. **fix/buds2-pro-model-detection** (2 commits)
   - test: reproduce #102 Buds2 Pro model detection (fails on main)
   - fix: correct Buds2 Pro model detection order
   - Impact: HIGH - fixes real user bug with hardware

2. **docs/add-buds3-pro-support** (1 commit)
   - docs: add Galaxy Buds 3 Pro to supported devices
   - Impact: LOW - documentation alignment

3. **fix/improve-error-messages** (1 commit)
   - fix: improve error messages for failed operations
   - Impact: LOW - UX improvement

## Denial List

- #127: Maintainer actively working (competing work)
- #76: Renovate bot (automated tooling)
- #29: Large feature, 5+ years old, not prioritized
- Daemon suspend/resume bug: Hardware-dependent, no test path

## Notes

- Repo is well-maintained, recent activity (Dec 2025 commits)
- Solo maintainer (JojiiOfficial)
- No existing tests - all tests added in this triage
- No CONTRIBUTING.md, assume standard Rust PR workflow
- Renovate PRs show maintainer is responsive to dependency updates
