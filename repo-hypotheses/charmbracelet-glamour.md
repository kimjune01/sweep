# Triage Graph: charmbracelet/glamour

**Repo**: charmbracelet/glamour  
**Type**: Go markdown renderer library  
**Org**: charmbracelet (warm - lipgloss PR #356 open)  
**Session**: 2026-05-10

## Denylist

None yet.

## Investigated Issues

### #518: Redundant tokyo_night.json theme ✓ QUEUED
- **Type**: Cleanup
- **Branch**: remove-tokyo-night-duplicate
- **Commit**: a48d3c7
- **Finding**: Orphaned duplicate from original PR #229, before kebab-case convention
- **Codex review**: LGTM with note about potential external string-based usage
- **Status**: Committed, in drip queue

### #503: Escaped tildes not rendering correctly ✓ QUEUED
- **Type**: Bug fix
- **Branch**: fix-escaped-tildes
- **Commit**: da7e85b
- **Finding**: Incomplete escapeReplacer missing ~, @, $, etc
- **Solution**: Replaced with CommonMark-compliant unescapeMarkdown()
- **Codex review**: Caught double-unescape issue, recommended centralized approach
- **Gemini review**: Approved with fast-path and byte-range optimizations
- **Status**: Committed with optimizations, in drip queue

### #505: wordwrap edge case
- **Type**: Upstream dependency bug
- **Finding**: lipgloss.Wrap issue, not glamour-specific
- **Status**: SKIP (we have open PR at lipgloss already)

### #545: glow.yml style key not expanded
- **Type**: Misfiled (glow CLI issue, not glamour library)
- **Status**: SKIP

### #548: Compact table layout
- **Type**: Feature request
- **Status**: SKIP (features don't merge at cold repos)

### #547: Markdown footnote elements
- **Type**: Feature request, author wants to implement
- **Status**: SKIP

## Stats

- Issues scanned: 7
- Bugs fixed: 2
- Queued for drip: 2
- Skipped: 5 (1 upstream, 1 misfiled, 3 features)

## Next Steps

Wait for drip to push PRs. Both fixes are clean, tested, and reviewed by codex + gemini.
