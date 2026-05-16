# denisidoro/navi -- Triage Graph

**Repo:** https://github.com/denisidoro/navi (17K stars, Rust CLI cheatsheet tool)
**Triaged:** 2026-05-09
**Open PRs:** 3 (none competing with our targets)
**Active maintainers:** denisidoro (owner), alexis-opolka (collaborator)

## Selected: #917 -- thread 'main' panicked on specific cheatsheet

- **Root cause:** `without_prefix` in `src/parser.rs` used byte-indexing `line[2..]`. Non-breaking space `\u{a0}` after `#` is 2 bytes in UTF-8, so byte index 2 lands inside the character, triggering a panic.
- **Fix:** Skip only the 1-byte ASCII prefix character (`#`, `%`, `@`) and let `.trim()` strip all Unicode whitespace. Also fixed dormant panic in `without_first` for multi-byte first chars.
- **Branch:** `fix/parser-panic-multibyte-prefix`
- **Commit:** c844c37
- **Reviews:** codex (pass, suggested extra test case -- applied), Gemini 3.1 Pro (pass, recommended simpler approach skip-1-then-trim -- applied, also caught dormant `without_first` bug)
- **Rounds:** 2 (initial impl + Gemini-driven simplification)
- **Tests:** 22/22 pass (3 new tests: multibyte, ascii, short inputs including exact panic case)
- **Status:** Ready to PR. In drip queue.

## Evaluated and deferred

### #862 -- `navi info cheats-path` ignores `$NAVI_PATH` and `$NAVI_CONFIG`
- **Type:** Bug, 2 thumbs-up
- **Actionability:** High. Clear repro. Fix is in `src/commands/info.rs` -- need to read env vars before falling back to defaults.
- **Why deferred:** #917 is a panic (higher severity). Queue #862 for next cycle.

### #882 -- searching doesn't work for descriptions longer than terminal size
- **Type:** Bug, 0 comments
- **Actionability:** Medium. Likely fzf truncation issue -- may need `--no-hscroll` or passing full text to fzf separately from display.
- **Why deferred:** No maintainer engagement. Needs investigation into fzf integration layer.

### #878 -- zsh widget results vary with terminal width
- **Type:** Bug, 0 comments
- **Actionability:** Medium. Related to #882 (both involve terminal width affecting results). Config-dependent.
- **Why deferred:** No maintainer engagement, likely same root cause as #882.

### #904 -- Empty output when a variable only contains `fzf` options
- **Type:** Bug, 0 comments
- **Actionability:** Low-medium. Edge case in variable parsing -- `---` options without a command body.
- **Why deferred:** No maintainer engagement, niche use case.

### #936 -- fish plugin errors when invoked in an empty command line
- **Type:** Bug, 1 comment (welcome bot)
- **Actionability:** Medium. Shell integration fix.
- **Why deferred:** Fish shell integration has active PRs (1013, 1017, 1024) from other contributors. Collision risk.

### #900 -- ZSH widget doesn't work with VI mode
- **Type:** Bug, 2 comments
- **Actionability:** Medium. Needs zsh bindkey investigation.
- **Why deferred:** Shell integration, less mechanical than parser fix.

## Repo signals

- **Merge velocity:** Slow. Last merge was PR #962 (March 2026). Owner responds but reviews slowly.
- **PR style:** Small, focused fixes. No feature PRs from external contributors merged recently.
- **Test infrastructure:** Unit tests in `src/`, integration test in `tests/tests.rs`. `cargo test` is the gate.
- **Strategy:** Bug fixes only. Earn trust with #917, then #862 as second PR.
