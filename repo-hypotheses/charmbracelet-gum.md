# charmbracelet/gum Triage Graph

## Session: 2026-05-10

### Repo Context
- **Org**: charmbracelet (warm - lipgloss PR open)
- **Type**: Go shell TUI toolkit
- **Stars**: 23K
- **Status**: Active development

### Issue Scan Results

#### Investigated Issues

1. **#967 - gum log misbehaves if context var is named "time"** ✅ FIXED
   - **Status**: Clear repro, no competing PR
   - **Root cause**: charmbracelet/log treats "time" as reserved field
   - **Solution**: Wrap reserved keys in structuredLogKey type implementing fmt.Stringer
   - **Testing**: Verified with text, json, logfmt formatters
   - **Quality gates**: Codex approved, Gemini approved with enhancements (added MarshalText)
   - **Branch**: fix-log-reserved-keys-967
   - **Commit**: b35f725

2. **#701 - bad scoring: gum filter fuzzy sort**
   - **Status**: Maintainer acknowledged, no competing PR
   - **Complexity**: High - requires algorithmic changes to fuzzy scoring
   - **Decision**: Deferred - needs deeper investigation into fuzzy library

3. **#1001 - crash on filter when wrapping after reflow**
   - **Status**: Clear repro, no competing PR
   - **Complexity**: Medium - terminal resize handling
   - **Decision**: Deferred - needs viewport state analysis

4. **#1025 - gum file removes first line**
   - **Status**: Maintainer acknowledged
   - **Competing PR**: #1031 open
   - **Decision**: Skip - competing work

#### Excluded Issues

- **#792, #788, #787, #786, #727, #688**: All have open or closed PRs
- **#797**: Closed PR #1053 attempted fix
- **#984**: Duplicate of #895, upstream dependency issue
- **#1022, #1020, #1017, #1011**: All have competing PRs

### Hypothesis Evidence

- **H1 (Warm orgs)**: ✅ charmbracelet has open lipgloss PR, indicating org-level engagement
- **H2 (Acknowledged bugs)**: ✅ #967 had clear bug report with repro steps
- **H3 (No competing PRs)**: ✅ #967 had no competing work
- **H4 (Test gates)**: ✅ Both codex and gemini reviews passed
- **H5 (Quality before speed)**: ✅ Added MarshalText per Gemini feedback

### Outcome

- **PRs created**: 1 (fix-log-reserved-keys-967)
- **Lines changed**: +40 -1
- **Test coverage**: Manual testing with 3 formatters (text, json, logfmt)
- **Review rounds**: 2 (codex → gemini)
- **Status**: Ready for drip queue
