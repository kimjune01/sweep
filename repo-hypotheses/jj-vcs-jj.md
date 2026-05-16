# Triage Graph: jj-vcs/jj

Generated: 2026-05-09

## Repo Profile

- **Stars:** 14K+
- **Language:** Rust
- **Domain:** Version control system (Git-compatible)
- **Maintainers:** martinvonz (lead/creator), ilyagr, yuja, bnjmnt4n
- **Review culture:** Thorough and constructive. Template/CLI changes reviewed carefully for consistency with existing patterns. Integration tests expected. Commit messages follow conventional format (area: description).

## Issue Scan

### Investigated

| Issue | Title | Labels | Verdict | Notes |
|-------|-------|--------|---------|-------|
| #9375 | op log -d should support redacted output | Enhancement | **SELECTED** | Maintainer-acknowledged. Template gap -- `builtin_op_log_redacted` exists but commit summaries within op log diffs are not redacted. Clean template-level fix. |

### Competing PR Density

- Moderate PR volume (~30 open)
- Many from core team (martinvonz, ilyagr)
- Template changes are low-conflict
- No competing PR for #9375

## Selected: #9375

### Hypothesis

**H0:** When using `builtin_op_log_redacted` template with `jj op log -d`, the op log header is redacted but the commit summaries within diffs still show descriptions and bookmark names in cleartext.

### Evidence

- Issue #9375 reports the gap explicitly
- `builtin_log_redacted` already exists as a pattern for how redaction should work
- The commit summary template used by op log diffs doesn't have a redacted variant

### Fix

- Added `commit_summary_redacted` template alias in `templates.toml`
- Added `format_commit_summary_with_refs_redacted` helper that redacts descriptions and bookmark names
- Follows the pattern of existing `builtin_log_redacted`
- Users combine via: `jj op log -Tbuiltin_op_log_redacted -d --config templates.commit_summary=commit_summary_redacted`

### Branch

`redacted-op-log-commit-summary` on `kimjune01/jj`

1 commit:
1. `templates: add commit_summary_redacted for redacted op log diffs` -- template + integration tests

6 files changed, 83 insertions: templates.toml, 5 test files

## Next Steps

1. Push via drip queue
2. If merged: look for other template gaps or CLI UX issues
3. jj has a welcoming contribution culture -- good candidate for sustained contributions
