# Triage Graph: red-data-tools/YouPlot

**Repo**: https://github.com/red-data-tools/YouPlot  
**Language**: Ruby  
**Stars**: 4.7K  
**Description**: A command line tool that draws plots on the terminal  
**Triaged**: 2026-05-10

## Summary

First contribution to YouPlot, a popular Ruby CLI for terminal plotting. Successfully implemented issue #44 (format bar labels as integers) after codex and gemini review. Clean implementation that handles edge cases (NaN, Infinity) and passes all existing tests.

## Scoring Results

Scored 17 open issues. Top 5 by actionability:

1. **#44** - Format bar labels as integer (11/12) ✓ IMPLEMENTED
2. **#38** - Count height parameter bug (10/12)
3. **#55** - Rotate Y-axis labels (8/12)
4. **#43** - Log scales for line/scatter (8/12) 
5. **#2** - Progressive mode improvements (8/12)

## Denied Issues

- **#49**: Pie chart - maintainer explicitly rejected ("I don't want to implement pie charts")
- **#57**: Left-align labels - maintainer said wrong repo (UnicodePlot upstream)
- **#46**: Ugly line charts - font issue, not a YouPlot bug
- **#39**: Config file not detected - likely user error, no maintainer response
- **#28**: Font question - not a bug or feature request
- **#22**: Categorical data - no details provided
- **#62**: Natural sort integers - CLOSED, fixed in da6351c

## Issue #44 Implementation

**Status**: READY FOR DRIP  
**Branch**: `fix-bar-integer-labels`  
**Commit**: fe117be  

### What Was Done

Implemented integer formatting for bar chart values when they have no fractional part:
- `3.0` → `3`
- `4.0` → `4`
- `3.5` stays `3.5` (preserves fractional values)

Added `normalize_numeric_value` helper that:
- Handles NaN/Infinity gracefully (returns unchanged)
- Converts whole-number floats to integers for cleaner display
- Forces integer conversion for count mode

### Review Process

1. **Codex review**: Suggested renaming from `format_numeric_value` to `normalize_numeric_value`, removing redundant comment. Applied.
2. **Gemini review**: Caught NaN/Infinity crash risk. Fixed with `.finite?` check.
3. **Tests**: All 103 tests pass, fixture updated

### Files Changed

- `lib/youplot/backends/unicode_plot.rb`: Added helper, updated barplot
- `test/fixtures/iris-barplot.txt`: Updated expected output

## Maintainer Context

**kojix2** (maintainer):
- Active and responsive
- Merges PRs regularly (dependabot, docs, typos)
- Said in #44: "I don't have much time for OSS these days"
- Partially fixed #44 in da6351c (count command only)
- Acknowledged remaining work needed for bar command

## Repository Notes

- **Wrapper architecture**: YouPlot wraps UnicodePlot.rb, which wraps UnicodePlot.jl (Julia)
- **Upstream dependency**: Many feature requests blocked on UnicodePlot improvements
- **Test suite**: Well-tested, 92.5% coverage
- **First contribution**: This is first OSS contribution to YouPlot

## Next Steps

1. Wait for drip to push PR
2. If merged: Consider #38 (height parameter) or #2 (progressive mode)
3. Track merge patterns for retro
