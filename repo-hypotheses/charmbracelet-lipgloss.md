# Triage Graph: charmbracelet/lipgloss

## Scan (2026-05-09)

User: kimjune01. 8.5K stars, Go terminal layout styling.
Status: First contribution (sibling repo bubbletea has existing PR). Bug fix with tests.

### Triaged issues

| # | Score | Signal | Title | Fix branch | Gate | Status |
|---|-------|--------|-------|------------|------|--------|
| 112 | 4 | Bug, wrong height calculation with wide-rune borders | Border.GetTopSize/GetBottomSize return rune width instead of row count | `fix/border-top-bottom-size` | test: PASS | READY |

### Fix details

**#112** (2 files, +102 -8)
- File: `borders.go` (+14 -8)
  - `GetTopSize()`: was `getBorderEdgeWidth(b.TopLeft, b.Top, b.TopRight)`, now returns 1 if any top border part is set, 0 otherwise
  - `GetBottomSize()`: same fix for bottom border
  - Root cause: Top/bottom borders always occupy exactly one terminal row regardless of display width of their rune characters. The old `maxRuneWidth` approach incorrectly returned >1 for wide-rune characters (e.g. emoji `"⏩"`), causing `GetVerticalBorderSize` to overcount and `Style.Render` to compute wrong heights
- File: `borders_test.go` (+88)
  - Test cases: normal border, empty border, wide-rune corner, partial borders (top-only, bottom-only)

### Competing PRs

None found for #112.

### Notes

charmbracelet org already has a PR from kimjune01 on bubbletea (#1689). Lipgloss is a sibling repo, so org familiarity exists.
