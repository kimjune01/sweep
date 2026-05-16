# Triage Graph: ratatui/ratatui

Generated: 2026-05-09

## Repo Profile

- **Stars:** 20K+
- **Language:** Rust
- **Domain:** TUI framework
- **Maintainers:** joshka (lead), orhun, kdheepak
- **Review culture:** Thorough. Breaking changes labeled, design discussions expected. Codex/AI PRs being tested by maintainers themselves (#2178).

## Issue Scan

### Investigated

| Issue | Title | Labels | Verdict | Notes |
|-------|-------|--------|---------|-------|
| #2311 | Spacing::Overlap + Constraint::Ratio don't work together | Type: Bug | **SELECTED** | Confirmed by maintainer. No competing PR. Clear repro. Mechanical fix in constraint solver. |
| #2421 | Fix clamping in list navigation method | Bug, Good First Issue | Skip | Claimed by Logan-Ruf, competing PR #2424 exists |
| #2340 | Paragraph doesn't apply Line styles to entire line | Bug | Skip | PR attempt got pushback from orhun. Design disagreement. |
| #2293 | Scrollbar color inconsistency | Bug | Skip | kdheepak marked "working as intended" -- it's a style inheritance issue |
| #1920 | Scrollbar thumb has inconsistent length | Bug | Skip | joshka says intentional design choice. Maintainer redirects to tui-scrollbar crate |
| #2178 | Use cargo-hack for cargo-rdme in xtask | Bug | Skip | Blocked by upstream cargo-rdme bug |
| #1347 | crossterm Stylize import collision | Bug | Skip | rust-analyzer issue, not ratatui. FAQ material. |
| #1402 | TestBackend buffer color assert | Enhancement, Good First Issue | Next candidate | Long discussion (13 comments), multiple approaches proposed. Needs design consensus first. |
| #1015 | Better Paragraph/Text/Line/Span style tests | Enhancement, Good First Issue | Next candidate | Test-only, low risk. Someone started but didn't finish. |

### Competing PR Density

- 48 open PRs total
- Many are maintainer-authored (joshka) or long-running features
- Dependabot PRs active
- AI-authored PRs being experimented with (#2178)

## Selected: #2311

### Hypothesis

**H0:** Ratio and Percentage constraints ignore overlap spacing when computing target segment sizes, causing segments to be undersized.

### Evidence

- Bug report provides exact reproduction code
- Maintainer (joshka) confirmed with "Thanks for the report - can confirm this"
- No competing PR found (searched all open + closed PRs mentioning 2311)
- Root cause identified: `configure_constraints` uses `area.size()` directly for Ratio/Percentage without adjusting for overlap

### Fix

- Modified `configure_constraints` to compute `effective_area = area.size() + overlap * (n_segments - 1)` for fixed-spacing flex modes
- Gated to Legacy/Start/Center/End (distributed flex modes use spacing as growth input, not fixed gap)
- Added 8 parametrized test cases + 1 guard test for distributed flex modes

### Review Trail

1. **Codex (GPT-5.5):** Found 3 structural issues -- (1) adjustment applied to all flex modes (fixed), (2) test width derivation fragile (fixed), (3) extract effective_area before loop (fixed)
2. **Gemini 3.1 Pro:** Validated math and gating. Found i16::MIN overflow risk in negation (fixed). Incorrectly flagged `.clone()` on Expression as unnecessary (it's needed -- Expression is Clone, not Copy).

### Branch

`fix/ratio-overlap-spacing` on `kimjune01/ratatui`

4 commits:
1. `fix(layout): account for overlap in Ratio and Percentage constraints` -- initial fix + tests
2. `fix(layout): gate overlap adjustment to fixed-spacing flex modes` -- codex review fixes
3. `fix(layout): negate spacing as f64 to avoid i16::MIN overflow` -- gemini review fix
4. `style: apply cargo fmt` -- formatting

## Next Steps

1. Open PR via drip queue
2. If merged: consider #1015 (style tests) or #1402 (TestBackend color assert) as follow-up
3. Pipeline target: 3 merged PRs before attempting feature contributions
