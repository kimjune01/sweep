# TRIAGE GRAPH: mattgodbolt/jsbeeb

## MAINTAINER PREFERENCES

**Target branch**: master (default)
**Max commits per PR**: Not specified in CONTRIBUTING.md (none found)
**CLA requirements**: None specified
**Contributing guidelines**: No CONTRIBUTING.md found

## ISSUE #631: Mouse coordinate calculation bug with display filters

**Status**: FIXED (queued for drip)
**Branch**: fix-mouse-coordinate-calculation
**Commits**: 2 (test + fix)
**SHA**: 1a69637f8c5c95887c583fbf414adf1cc3cda86a

### Bug Hunt Analysis

**Mechanism**: The `onCubMouseEvent` function converts browser mouse coordinates to normalized [0,1] coordinates for touchscreen and mouse joystick features.

**Why the bug existed**: Lines 541-542 mixed `evt.offsetX/Y` (relative to event target) with bounding rect calculations:
```js
const x = (evt.offsetX - cubRect.left + screenRect.left) / screenCanvas.offsetWidth;
const y = (evt.offsetY - cubRect.top + screenRect.top) / screenCanvas.offsetHeight;
```

This geometric nonsense worked by accident when canvas had no inset (display filter off), because `cubRect.left == screenRect.left` so the operations canceled out. But failed with display filters.

**Wrong fix would be**: Using `evt.pageX/Y` (doesn't account for scroll), or fixing numerator without denominator.

**Devil's advocate**: "Not a bug because it works in production." Counter: latent bug, only manifests with display filters enabled.

### Implementation

**Test**: `tests/unit/test-mouse-coordinates.js`
- Demonstrates bug with inset canvas (display filters)
- Validates correct behavior with and without filters
- First commit: `1247f05 test: reproduce #631 (fails with display filters)`

**Fix**: Changed to use `evt.clientX/clientY` against screen canvas rect directly:
```js
const x = (evt.clientX - screenRect.left) / screenRect.width;
const y = (evt.clientY - screenRect.top) / screenRect.height;
```
- Second commit: `1a69637 fix: use clientX/Y for mouse coordinates (#631)`
- All unit tests pass (595 tests)

### Hypothesis

**H3 (latent bugs)**: This is a latent bug that manifested only with specific feature combinations (display filters). Test-first approach exposed it cleanly.

---

## TRIAGE SUMMARY

**Total issues scanned**: 43 open issues
**Actionable bugs found**: 1 (#631)
**Implemented**: 1
**Reason for stopping after 1 issue**: 
- Solo-maintainer repo (mattgodbolt)
- First contribution to this repo
- 386 stars (mid-size)
- Following memory guideline: "For solo-maintainer repos (first contribution), prefer the smallest/easiest issue"
- Issue #631 was well-defined with clear reproduction and fix
- Other bugs (#495, #494, #488) involve Safari/disc save complexity or have extensive discussion (43 comments)
- Conservative approach: earn trust with one clean bug fix before attempting more

---

## REPO METADATA

**Stars**: 386
**Open issues**: 43
**Type**: BBC Micro emulator (JavaScript)
**First contribution**: Yes
**Solo maintainer**: Yes (mattgodbolt)

**Strategy**: Small, well-tested bug fixes. Avoid complexity. This is a clear bug with reproduction path and comprehensive test coverage.
