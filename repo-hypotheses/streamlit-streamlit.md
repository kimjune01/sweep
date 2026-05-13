# Streamlit Triage Graph

**Repo**: streamlit/streamlit (45K stars, Python+TypeScript)  
**Date**: 2026-05-09  
**Good-first-issues scanned**: 10

## Issues Investigated

### #13005 - Integer/pixel gap parameter
- **Status**: 3 competing PRs (#14390, #14995, plus earlier)
- **Complexity**: Backend (proto) + frontend (React)
- **Verdict**: Crowded

### #12805 - Use theme colors in st.map ✅ **SELECTED**
- **Status**: 1 closed PR (#12817) - broke gradients
- **Complexity**: Backend-only, single constant change
- **Competing PRs**: None open
- **Acceptance criteria**: 
  - Change default marker color from red to blue
  - Match Streamlit's chart color scheme
  - Don't touch gradients or user-specified colors
- **Implementation**: 
  - Changed `_DEFAULT_COLOR` from `(200, 30, 0, 160)` to `(0, 104, 201, 160)`
  - Single-line change in `lib/streamlit/elements/map.py`
  - Scoped to default single-color case only
- **Maintainer signal**: Issue author @jrieke is a COLLABORATOR
- **Commit**: `49dfc59da` on `fix/map-theme-color-12805`

### #12217 - Add height="stretch" to st.tabs
- **Status**: 1 active PR (#14850, last updated recently)
- **Verdict**: Skip - PR in flight

### #11643 - Show hex colors in Markdown
- **Status**: 1 PR (#14942)
- **Verdict**: Skip - PR exists

### #11559 - WSL2 build issue
- **Type**: Dev environment enhancement
- **Verdict**: Not user-facing, low pipeline value

### #11346 - Tick styling in bokeh
- **Type**: Bug (P3), upstream dependency
- **Complexity**: Uncertain (upstream issue)
- **Verdict**: Skip - upstream complexity

### #10906 - HTML validation popup
- **Status**: 2 PRs (#11533 closed, #13747 open, #14947 active May 2)
- **Verdict**: Skip - active PR

### #9934 - Tooltip when label hidden
- **Status**: 1 PR (#13792, Feb 2026)
- **Complexity**: Frontend, touch every widget component
- **Verdict**: Skip - broad scope

### #9272 - Custom LaTeX delimiters
- **Status**: No competing PRs
- **Complexity**: Backend (proto + API) + frontend (KaTeX config)
- **Scope**: Multi-function (markdown, write, write_stream)
- **Verdict**: High value but complex for first PR

### #9098 - SVG display without width
- **Status**: 2 PRs (#14996 active May 1, earlier by ManasVardhan)
- **Type**: Frontend-only (ImageList.tsx)
- **Verdict**: Skip - 2 competing implementations

## Selection Rationale

Chose **#12805** because:
1. **Zero competing PRs** (closed PR failed due to over-scope)
2. **Smallest possible scope** - one constant, one line
3. **Clear acceptance** - maintainer-authored issue
4. **Hypothesis test**: "minimal backend changes merge faster than frontend/proto work"
5. **Scoped from failure** - kimimgo's March comment outlined the minimal fix after #12817 broke gradients

## Repository Characteristics

- **Maintainer velocity**: Active (multiple PRs reviewed in past week)
- **Good-first-issue quality**: Mix of truly simple (this one) and mislabeled complex (LaTeX, tabs)
- **Competing PR density**: High - 7 of 10 issues had open PRs
- **Review lag**: Varies - some PRs get quick LGTM, others stall
- **Architecture**: Backend (Python/proto) + Frontend (React/TypeScript) split means most features touch 2+ layers
