# amsynth/amsynth Triage Graph

**Repo**: amsynth/amsynth (493★, C++)
**Description**: Simple software synthesizer for Linux
**Triage Date**: 2026-05-11

## Repository Assessment

**Maintainer**: nickdowell (Nick Dowell) - MEMBER, responsive
**Activity**: Active development, JUCE UI rewrite in progress (branch `develop`)
**Recent Merges**: Georgian translation (2026-02), NSM keys (2024-10)
**PR Pattern**: Small, focused changes merge. Recent typo PR #228 CLOSED (redundant with larger work).

## Issues Triaged

### #95 - Open control input field with middle click (IMPLEMENTED)
**Status**: Feature request, 2017-06-22, 0 comments
**Actionability**: HIGH - clear spec, no competing work
**Implementation**: middle-click-text-input branch
- Added `middleMouseDown` virtual method to Control base class
- Implemented AlertWindow with TextEditor for Knob class
- Input validation (numeric only), clamping to param range
- X11-specific focus handling for Linux
- Files: Controls.cpp (+52), Controls.h (+2)
- Pattern: Follows existing MainComponent modal dialog approach

**Devil's Advocate**: 
- Q: Does JUCE support middle-click properly on all platforms?
- A: Yes, `event.mods.isMiddleButtonDown()` is cross-platform
- Q: Should this be configurable (middle vs double-click)?
- A: Start simple. Double-click already resets to default. Middle-click is unused.
- Q: Input validation sufficient?
- A: Restricts to "0123456789.-", clamps to range. Good enough for v1.

**Self-Review**:
- ✓ Follows JUCE patterns from MainComponent
- ✓ Proper edit begin/end for undo
- ✓ Label updates after value set
- ✓ Platform-specific focus handling
- ✓ No memory leaks (callback deletes AlertWindow)

### #87 - Make ./configure fail if dependencies are missing (IMPLEMENTED)
**Status**: Build system issue, 2017-06-09, 2 comments from maintainer
**Actionability**: HIGH - maintainer acknowledges problem, suggests autotools.io pattern
**Implementation**: fix-configure-dependency-check branch
- Modified configure.ac to distinguish explicit `--with-X=yes` from auto-detect
- Explicit requests now fail fast if dependency missing
- Auto-detect remains soft-fail (backward compatible)
- Affects: ALSA, JACK, LASH, NSM, DSSI
- Files: configure.ac (+25/-6)

**Devil's Advocate**:
- Q: Does this break existing build scripts?
- A: No. Only changes behavior when user explicitly passes `--with-X=yes`
- Q: What about OSS (uses AC_CHECK_HEADERS)?
- A: OSS uses header check, not pkg-config. Different pattern, leave as-is for this PR.
- Q: Should pandoc get same treatment?
- A: Already has it (lines 161-165), explicitly errors when --with-pandoc=yes

**Self-Review**:
- ✓ Follows autotools.io best practice
- ✓ Backward compatible (auto-detect unchanged)
- ✓ Consistent with existing pandoc pattern
- ✓ Clear error messages from PKG_CHECK_MODULES

### Issues Skipped

**#239 - LV2 control stream issue**: Status: Resolved (maintainer already fixed on develop)
**#235 - Noise 1.12.2→1.12.3**: Status: Resolved (maintainer already reverted offending commit)
**#241 - Pulse width modulation**: Feature request, too broad, no clear spec
**#171 - Sub-oscillator**: Feature request, needs DSP design, too complex for standing
**#146 - Unison parameter**: Feature request, maintainer interested but no clear spec
**#15 - LFO tempo sync**: Feature request, requires MIDI/JACK tempo, complex

## Hypothesis Classification

### #95 (middle-click text input)
- **H0 (Clear Acceptance)**: YES - Feature request with no competing work
- **H2 (Clean Implementation)**: YES - Follows existing JUCE patterns
- **H5 (Maintainer Alignment)**: LIKELY - UI improvement, low risk

### #87 (configure dependency check)
- **H0 (Clear Acceptance)**: YES - Maintainer explicitly referenced autotools.io pattern
- **H1 (Test-Driven)**: N/A - Build system change
- **H2 (Clean Implementation)**: YES - Minimal, targeted change
- **H5 (Maintainer Alignment)**: HIGH - Maintainer's own suggestion from 2020

## Standing Strategy

Both PRs demonstrate:
1. **Minimal surface area** - Small, focused changes
2. **Maintainer-acknowledged problems** - Both issues have maintainer engagement
3. **No competing work** - No existing PRs or branches
4. **Pattern-following** - JUCE conventions (#95), autotools best practice (#87)

Expected outcome: Merge or constructive feedback. Both address long-standing issues (2017).
