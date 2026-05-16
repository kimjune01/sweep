# Triage Graph for NiklasRosenstein/pydoc-markdown

## Fixed Issues

### [Issue #197] Bootstrap and Poetry Conflict
- **Status**: ✅ Fixed (commit 89ee8fa, on develop branch)
- **Summary**: The `--bootstrap` command failed if `pyproject.toml` existed, even if it didn't contain `pydoc-markdown` configuration.
- **Fix**: Modified `main.py` to check if `pyproject.toml` contains `[tool.pydoc-markdown]` before failing. Added `tomli` import to `main.py`.
- **Branch**: develop
- **Commit**: `89ee8fa`
- **PR**: Ready for upstream (already on develop)

### [Issue #125] Uniquify Markdown Anchor References
- **Status**: ✅ Fixed (commit e6308a9, on branch fix/uniquify-markdown-references)
- **Summary**: When multiple API objects used the same markdown reference-style link IDs (e.g., `[text][0]`), they would conflict when rendered into the same document, causing broken links.
- **Fix**: Added `_uniquify_markdown_references()` method to MarkdownRenderer that prefixes all reference IDs with the object name (e.g., `[text][a-0]`) to guarantee global uniqueness. 
- **Branch**: fix/uniquify-markdown-references
- **Commit**: `e6308a9`
- **Tests**: test/test_duplicate_markdown_refs.py (3 passing tests), all existing tests pass
- **PR**: Ready for upstream

### [Issue #296] Google Style Docstring Code Block Rendering
- **Status**: 🟡 WIP (commit d953b9f, round 2/3)
- **Summary**: Code blocks in Google-style Examples sections retain extra indentation (4+ spaces) and render incorrectly - backticks appear as literal text instead of code blocks
- **Root Cause**: GoogleProcessor strips all lines with `line.strip()`, then adds "  " prefix for section content. This causes code blocks to have 4+ spaces, triggering Markdown's "indented code block" behavior which conflicts with fenced code blocks.
- **Fix Implemented**:
  - Track code block boundaries with `in_codeblock` flag
  - Calculate base indentation when entering code block: `codeblock_base_indent = len(line) - len(line.lstrip())`
  - Remove base indentation from code block content while preserving relative indentation
  - Use `line.lstrip()` for backticks to ensure flush-left rendering
- **Branch**: fix/google-codeblock-indentation
- **Commit**: `d953b9f`
- **Tests**: Created test/test_google_codeblock.py (1 passing test)
- **Remaining Work**: Update expectations in test/processors/test_google.py (2 test cases need updating)
- **Next Round**: Update test expectations and verify fix

## In-Progress Issues

### [Issue #297] Google Style Docstring Variable Name Duplication
- **Summary**: Args entries with >10 parameters show repeated variable names for entries 10+
- **Investigation**: Related to `escape_html_in_docstring` parameter - when set to true, produces buggy docstrings
- **Competing PRs**: None
- **Complexity**: Medium - requires investigation of escape_html logic
- **Next Action**: Needs deeper investigation

## Investigated Issues (Not Started)

### [Issue #154] Include Page Source Files in Watchlist
- **Summary**: `--server` option doesn't watch `Page.source` files for changes
- **Investigation**: MkDocs/Hugo renderers allow `Page.source` files, but they're not included in the watchlist
- **Competing PRs**: None
- **Complexity**: Low - feature add to watch list
- **Next Action**: Investigate watch implementation

### [Issue #272] SyntaxError with Metaclasses
- **Summary**: Rendering a class with only a metaclass supposedly produces invalid code
- **Investigation**: `MarkdownRenderer` produces `class MyClass(metaclass=MyMeta)`, which is valid Python 3
- **Status**: Needs reproduction - may be fixed or environment-specific

### [Issue #238] AttributeError in Configuration Loading
- **Summary**: `Location` object missing `Format` attribute
- **Investigation**: Searched for `.Format` in codebase - no matches in pydoc-markdown source
- **Status**: May be fixed or dependency issue

### [Issue #182] Google Docstring Tab Length
- **Summary**: Google docstring parsing expects tab length of 2 but user has tab length of 4
- **Competing PRs**: None
- **Complexity**: Low - configuration/documentation issue

## Repository Stats
- **Stars**: 498
- **Language**: Python
- **Open Issues**: 50
- **Open PRs**: 13 (checked for conflicts)

## Repository Structure
- `src/pydoc_markdown`: Core logic
  - `main.py`: CLI entry point
  - `contrib/loaders`: Python loader (uses `docspec`)
  - `contrib/processors`: Google, Sphinx, Smart, CrossRef, Filter
  - `contrib/renderers`: Markdown, MkDocs, Hugo, Docusaurus, Jinja2
- `test`: Pytest suite
  - `test/processors`: Processor-specific tests
  - `test/renderers`: Renderer-specific tests
  - `test/utils.py`: Test utilities (assert_text_equals)

## Session Summary

**Completed**: 2 fixes
- Issue #125: Uniquify Markdown refs (clean, tested, ready for PR)
- Issue #197: Bootstrap Poetry conflict (already on develop)

**In Progress**: 1 fix (needs round 3)
- Issue #296: Google codeblock indentation (core fix done, test expectations need updating)

**Pipeline Next Steps**:
1. Complete issue #296 test updates (round 3)
2. Investigate issue #297 (variable duplication)
3. Implement issue #154 (watchlist)

**Learnings**:
- Test-first approach caught edge cases early
- Markdown indentation semantics: 4+ spaces = indented code block, conflicts with fenced blocks
- Google processor has existing test suite with specific formatting expectations
- Code block handling needs special care to preserve both indentation and markdown compatibility
