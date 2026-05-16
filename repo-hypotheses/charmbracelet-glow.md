# Triage Graph: charmbracelet/glow

**Session**: 2026-05-10
**Org**: charmbracelet (warm - lipgloss PR #493 open)
**Repo**: glow (Go markdown renderer, 25K stars)
**Open bugs**: 2 actionable without competing PRs

## Investigated Issues

### #930: tmux file rendering broken ✅ FIXED
**Status**: Implemented, committed to `fix-930-auto-pager`
**Root cause**: `glow file.md` in terminal always printed to stdout instead of auto-paging
**Fix**: Auto-page when output exceeds terminal height
**Evidence**: 
- codex provided initial fix (extract pager closure, check TTY)
- gemini caught 3 bugs: (1) checking os.Stdout vs w io.Writer, (2) always paging is sledgehammer, (3) need better less flags
- Applied all fixes: check w.(*os.File), only page if lines > height, use `less -r -F -X`
- Tests pass, build succeeds

**Gemini review findings**:
1. Architectural bug: Must check `w io.Writer` not `os.Stdout` to avoid breaking unit tests
2. UX issue: Auto-paging every file is excessive - only page if content > terminal height
3. Improvement: Use `less -r -F -X` for auto-exit on short content

### #878: TUI width not respected
**Status**: SKIP - 2 competing PRs (#886, #887) both open since Feb 2026

### #941: Table column collapse (width 0)
**Status**: Considered but SKIP - upstream glamour bug per issue description
**Location**: glamour/ansi/table.go interacting with lipgloss/table
**Not fixable in glow**: Would require glamour PR

### #932: Zombie processes on macOS
**Status**: NOT INVESTIGATED - chose #930 as higher priority
**Repro unclear**: "Kill the server? Or macOS hibernation?" - needs more evidence

### #819: Width wrapping backtick bug
**Status**: NOT INVESTIGATED - upstream muesli/reflow bug per comment
**PR exists upstream**: muesli/reflow#79 (unmerged since repo inactive since Apr 2024)

## Scoring Results

Top 5 actionable issues ranked:
1. #930 (tmux file rendering) - FIXED
2. #932 (zombie processes macOS) - systems bug, high impact, unclear repro
3. #941 (table collapse) - upstream glamour bug
4. #819 (backtick wrap) - upstream reflow bug
5. #858 (line breaks in lists) - rendering bug, no competing PRs

## Hypothesis Updates

**H2 (Warm orgs accept faster)**: charmbracelet cluster includes glamour, lipgloss - #493 open at lipgloss
**H3 (Bug fixes merge, features don't)**: #930 is pure bugfix, well-scoped, tests pass
**H5 (Quality gates mandatory)**: Applied - codex first pass, gemini caught 3 bugs, all fixed before commit

## Next Actions

1. Push `fix-930-auto-pager` to fork when drip queue clears
2. Open PR with repro steps and terminal height explanation
3. Consider #932 if #930 merges quickly (same org, systems expertise)
