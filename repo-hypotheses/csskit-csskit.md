# csskit/csskit Triage Graph

## Investigated Issues

### #770 - Comments maybe can't be replaced by whitespace in custom properties [FIXED]

**Status:** Fixed in branch `fix-770-comment-custom-property`

**Type:** Bug - Minifier

**Diagnosis:** When minifying CSS, comments between tokens were being replaced with whitespace. For custom properties used in container style queries, this changes the component value sequence:
- `--bar: a/**/b` (two idents with comment) became `--bar: a b` (two idents with whitespace)
- These are different component values per CSS spec

**Root Cause:** CursorCompactWriteSink was using `needs_separator_for()` to determine if whitespace should be inserted between tokens, but it didn't check if there was originally whitespace in the source (vs. only comments).

**Fix:** Added logic to check the source text gap between tokens. If only comments (no whitespace), don't add a separator. This allows tokens to merge naturally when comments are removed.

**Test:** Added `test_preserves_comment_absence_in_custom_properties` in `cursor_compact_write_sink.rs`

**Commits:**
1. `b9a497b0` - test: reproduce #770 (fails on main)
2. `3fbe236e` - fix: #770 preserve token separation when comments are removed

**Files Changed:**
- `crates/css_parse/src/cursor_compact_write_sink.rs`

## Issue Ranking

1. **#770** - Comments in custom properties bug - ✅ FIXED (edge case, spec compliance, small scope)
2. **#869** - SVG data URL minification bug (clear bug with expected output)
3. **#779** - Minify redundant shorthand values (enhancement, well-scoped)
4. **#842** - Add Prettier to playground (website feature, lower priority)
5. **#872** - Minify CSS relative colors (requires HIR implementation)

## Denylist

- #859 - Already assigned to @yisibl

## Repository Context

- 292 stars, solo maintainer (keithamus)
- CSS toolkit in Rust
- Focus: parsing, minification, linting
- Architecture: lexer → parser → AST → transformers
