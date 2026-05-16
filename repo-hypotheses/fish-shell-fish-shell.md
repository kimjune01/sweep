# fish-shell/fish-shell Triage Graph

## Repo Context
- **Language**: Rust + fish script
- **Build**: `cargo build`
- **Tests**: `python3 tests/test_driver.py target/debug tests/checks/git.fish`
- **Formatting**: `fish_indent` for .fish, `rustfmt` for .rs, `ruff format` for .py
- **Default branch**: master
- **Commit style**: Linear, recipe-style. No fixup commits. Rewrite history to fix relevant commits directly.
- **AI policy**: No explicit policy in CONTRIBUTING.rst. Community sentiment against LLM-heavy tools observed in #12701 discussion.
- **CLA**: None required.

## Investigated Issues

### #11296 — Renaming file starting with [ACDMRTU] breaks git prompt
- **Status**: fix implemented, qa_passed
- **Branch**: fix-git-prompt-rename-count
- **Root cause**: `git status --porcelain -z` outputs rename/copy source filename as a separate NUL-delimited field. After `string split0`, the bare filename gets counted as an additional staged/dirty entry when it starts with a character in [ACDMRTU].
- **Fix**: Filter `string split0` output through `string match -r '^[ MADRCU?!]{2} .*'` to keep only valid status entries.
- **Commits**: 2 (failing test + fix)
- **Maintainer signal**: faho (member) confirmed bug, suggested fix approach.

## Denied Issues
(none)

## Observations
- fish-shell is a well-maintained, active project with engaged maintainers (krobelus, faho, danielrainer).
- Bug fixes with tests are welcomed. First contribution should be small and clean.
- Community is quality-conscious and skeptical of AI-generated code (see #12701 comments about Tombi).
- CONTRIBUTING.rst requires `fish_indent` formatting and linear commit history.
