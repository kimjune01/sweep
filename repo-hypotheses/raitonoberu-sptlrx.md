# Triage Graph: raitonoberu/sptlrx

## Summary

**Repository:** raitonoberu/sptlrx (492★, Go, Spotify lyrics in terminal)  
**Issues analyzed:** 13 open issues  
**Branches created:** 5  
**Strategy:** Bug fixes + documentation improvements for standing

## Hypothesis

sptlrx has 13 open issues. Focus on small, clear improvements to establish standing before attempting larger features. Priority: bug fixes > typos > documentation gaps.

## Issues Analyzed

### Issue #55: Indicate when a lyric wasn't found

**Devil's Advocate Analysis:**

PRO:
- Clear, simple request: show message instead of blank terminal
- Easy to reproduce: play a song without lyrics
- User explicitly asked for this (edu-flores)
- Low complexity: single conditional in ui.go
- No external API changes needed
- Aligns with UX best practices (feedback over silence)

CON:
- Could be intentional design (minimal/zen aesthetic)
- Maintainer might prefer blank screen for scriptability
- Message text needs to be chosen carefully
- Might conflict with `ignoreErrors` config
- Could be seen as noise for users who pipe output

**Verdict:** Worth pursuing. The lack of feedback is a UX issue, not a design feature. The config already has `ignoreErrors` for users who want silence.

**Implementation plan:**
1. In `ui/ui.go`, modify the View() method
2. When `len(m.state.Lines) == 0 && m.state.Err == nil`, render a centered message
3. Message: "No lyrics found" (simple, clear, non-intrusive)
4. Use the same styling as error messages (current line style, centered)

### Issue #78: did new l;ogin method still black

**Analysis:** Title is unclear, comment from contributor is just "No". Not actionable without more context. Skip.

### Issue #76: Option to take next best result from LRCLIB

**Analysis:** Feature request requiring fuzzy matching logic. Complex change to search behavior. Not suitable for first PR. Skip.

### Issue #36: improved MPRIS query

**Analysis:** User provided clear motivation and even offered to implement. Adding album to query string. More complex than #55 but well-specified. Consider as second issue.

## Selected Issues

1. **Issue #55** (priority 1) - No lyrics found message ✓ FIXED
2. **Typo in README** - "plaftorm" -> "platform" ✓ FIXED
3. **Bug in config.go** - ColorWhitespace return value discarded ✓ FIXED

## Implemented Fixes

### 1. Issue #55: No lyrics found message (branch: fix/no-lyrics-message)

**Status:** Committed

**Analysis:** When no lyrics are available, the UI shows a blank screen with no feedback. This is poor UX.

**Implementation:** Modified `ui/ui.go` to display "No lyrics found" message (centered, using current line style) when `len(m.state.Lines) == 0`.

**Testing:** Code builds successfully. The change is minimal and low-risk.

**Commit:** `f929293 - Show 'No lyrics found' message instead of blank screen`

### 2. Typo fix (branch: fix/typo-platform)

**Status:** Committed

**Analysis:** README has typo "cross-plaftorm" instead of "cross-platform".

**Implementation:** Simple string replacement in README.md line 18.

**Commit:** `bf7fa6d - Fix typo: plaftorm -> platform`

### 3. ColorWhitespace bug (branch: fix/color-whitespace-assignment)

**Status:** Committed

**Analysis:** In `config/config.go` line 138, the return value of `style.ColorWhitespace(false)` was being discarded. This is a bug because lipgloss.Style uses an immutable builder pattern - each method returns a new Style instance.

**Impact:** The ColorWhitespace setting was never actually applied to styles with backgrounds.

**Implementation:** Changed `style.ColorWhitespace(false)` to `style = style.ColorWhitespace(false)`.

**Testing:** Code builds successfully.

**Commit:** `0878a31 - Fix ColorWhitespace return value being discarded`

### 4. Error message consistency (branch: fix/error-message-consistency)

**Status:** Committed

**Analysis:** In `cmd/login.go`, the error message says "client_id and client_secret are required" but the actual flags are `--client-id` and `--client-secret` (with hyphens, not underscores).

**Impact:** Users seeing this error message might be confused about the exact flags to use.

**Implementation:** Changed error message to use `--client-id` and `--client-secret` to match the actual flag names.

**Commit:** `ebe9b72 - Use consistent flag names in error message`

### 5. Missing browser player in documentation (branch: fix/document-browser-player)

**Status:** Committed

**Analysis:** README config comment lists "Possible values: spotify, mpd, mopidy, mpris" but omits "browser", which is a valid and documented player.

**Implementation:** Added "browser" to the list of possible player values in README.md line 57.

**Commit:** `518b4a4 - Add browser to list of possible player values`

## Branches Ready for Drip Queue

1. `fix/no-lyrics-message` - Fixes issue #55 (UX improvement)
2. `fix/typo-platform` - Documentation typo
3. `fix/color-whitespace-assignment` - Bug fix in style parsing
4. `fix/error-message-consistency` - Error message improvement
5. `fix/document-browser-player` - Documentation completeness

## Evidence for Hypothesis Testing

### H0 - Standing
- **fix/typo-platform**: Simple typo fix, low barrier to entry
- **fix/document-browser-player**: Documentation completeness, shows attention to detail
- **Prediction**: High merge probability, establishes contributor reliability

### H1 - Usability
- **fix/no-lyrics-message**: Addresses user-reported issue #55, clear UX improvement
- **fix/error-message-consistency**: Makes CLI error more helpful
- **Prediction**: Medium-high merge probability, maintainer values UX (evidence: config flexibility)

### H2 - Correctness
- **fix/color-whitespace-assignment**: Real bug, discarded return value
- **Prediction**: High merge probability if maintainer values correctness (lipgloss immutable pattern)

## Rejected Issues

- **#78**: Unclear title and no context, skipped
- **#76**: Feature request (fuzzy matching), too complex for first PR
- **#36**: Maintainer investigating API issue, blocked externally
- **#63**: Feature request (multi-player), requires architecture changes

## Next Steps

1. Wait for /drip to advance entries to "dripped" status
2. Use /ship to create PRs (not done in /triage)
3. Monitor for review feedback
4. If standing established (1-2 merges), revisit issue #36 or #38

