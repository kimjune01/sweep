# Triage Graph: storybookjs/storybook (kimjune01)

**Scan date:** 2026-05-09
**Mode:** dry-run

## Scan Table

| # | Title | State | Score | Effort | Signal | Status |
|---|-------|-------|-------|--------|--------|--------|
| 34691 | ArgsTable border visibility is poor in dark and high contrast modes | OPEN | 6/10 | Small (~15 lines TSX) | Maintainer-filed, accessibility | IMPLEMENTED |

## #34691: ArgsTable dark mode border visibility

### Root Cause

`appBorderColor` is white at 10% opacity (`rgba(255,255,255,0.1)`) in the dark theme. Against the dark content background, this is nearly invisible. All table borders (`borderTop`, `borderBlockStart/End`, `borderInlineStart/End`) use this token directly.

### Fix (~15 lines)

- Import `opacify` from `polished` (already a project dependency).
- Compute `tableBorderColor`: in dark mode, boost opacity by 0.1 via `opacify(0.1, theme.appBorderColor)`; in light mode, pass through unchanged.
- Replace all 5 border declarations to use `tableBorderColor`.
- Increase dark-mode `drop-shadow` opacity from 0.20 to 0.40.

### Review notes

- **Codex said:** drop polished/opacify, drop shadow change, keep forced-colors, use explicit dark border. Current implementation keeps polished — it is already a transitive dependency and `opacify` is more theme-resilient than a hardcoded color.
- **Forced-colors media query** (for Windows High Contrast) is a stretch goal, not yet implemented.
- **No competing PRs** found.

### File changed

- `code/addons/docs/src/blocks/components/ArgsTable/ArgsTable.tsx`
