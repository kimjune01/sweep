# Triage Graph: cucumber/gherkin

## Repo Profile
- Stars: 331 (200-500 bucket)
- Primary language: C (multi-language parser)
- Default branch: main
- Maintainer: mpkorstanje (M.P. Korstanje) — sole active maintainer
- 13 language implementations, CONTRIBUTING.md mandates cross-language consistency

## Maintainer Preferences (from CONTRIBUTING.md)
- Feature branches required
- Don't lump unrelated changes
- Changes should ideally be consistent across all implementations
- Cross-language consistency > elegant design in any single language
- Berp-generated parser — don't refactor to diverge from other implementations
- Test data lives in shared `testdata/` directory
- Acceptance tests compare output via `diff` against expected `.ndjson`/`.tokens` files

## Issues Investigated

### #454 — C: Segfault when one placeholder is a prefix of another [BUG] ✅ TRIAGED → QA_PASSED
- **Status:** Fix committed on branch `fix/454-segfault-prefix-placeholder`
- **Root cause:** C compiler's `create_expanded_text` used `wcsncmp` prefix match instead of exact `<placeholder>` match. When column "parent" preceded column "parentflag", both matched at the same position, producing overlapping replacement items that corrupted memory.
- **Fix:** Find closing `>` first, require exact length match. Added guard for missing `>`.
- **Scope:** C-only. Java/JS/Python implementations use `String.replace("<" + name + ">", value)` which is already correct.
- **Test:** `testdata/good/scenario_outline_prefix_placeholder.feature` with expected output files.
- **Competing PRs:** None
- **Commits:** 3 (test, fix, edge-case guard from Gemini review)

### #515 — dotnet: CONTRIBUTING is outdated [DOCS] ✅ TRIAGED
- **Status:** Fix committed on branch `fix/515-dotnet-contributing-outdated`
- **Root cause:** Document referenced .NET 5 with link to .NET Core 2 (both long EOL), mentioned Visual Studio 2019, used `master` branch links.
- **Fix:** Replace with link to CI workflow for prerequisites (won't go stale), update branch refs to `main`, remove VS2019 mention.
- **Scope:** Single file: `dotnet/CONTRIBUTING.md`
- **Competing PRs:** None
- **Commits:** 1

### #36 — javascript: Acceptance tests do not include tokens [DEBT] ✅ TRIAGED
- **Status:** Fix committed on branch `fix/36-javascript-token-acceptance-tests`
- **Root cause:** JavaScript was the only implementation missing token acceptance tests. The tokens were removed in cucumber/common#448 and never restored.
- **Fix:** Added `TokenFormatterBuilder` class (matching Python/Java/Ruby pattern), `generate-tokens-cli.mjs` script, and `$(TOKENS)` to Makefile acceptance target. Also fixed 3 bugs in `GherkinInMarkdownTokenMatcher` that the token tests exposed:
  - `match_Comment` did not set `matchedType` for GFM table separators (produced `undefined` token type)
  - `match_TagLine` did not call `setTokenMatched` (missing `location.column`)
  - `match_Empty` used line indent instead of 0 for neutered lines (wrong column)
- **Scope:** JavaScript-only. All 51 token files (46 `.feature` + 5 `.feature.md`) pass. All 36 unit tests pass. All 215 acceptance test diffs pass.
- **Competing PRs:** None
- **Commits:** 1

### #396 — Remove CLI from documentation [DOCS] ✅ TRIAGED
- **Status:** Fix committed on branch `fix/396-remove-cli-from-docs`
- **Root cause:** README documented a `gherkin` CLI command, but the CLI was only used for integration testing and most implementations no longer ship it as a user-facing binary.
- **Fix:** Removed CLI section from README, updated Usage section to describe Gherkin as a library, removed CLI reference in Pickles section.
- **Scope:** Single file: `README.md`
- **Competing PRs:** None
- **Commits:** 1

### #364 — Datatable parsing, wrongly escape regexp "\w" [BUG] — INVESTIGATED, DEFERRED
- **Why deferred:** Cross-language escaping semantics are complex. Maintainer said "Feel free to look into this deeper" but the fix needs to be consistent across all 13 implementations. Python's `split_table_cells` shows correct behavior on current main for simple cases, but the reporter's specific version (gherkin-official 29.0.0) may have had different behavior. Too risky for a first contribution.

### #552 — [cpp]: std::codecvt_utf8 deprecated since C++17, removed in C++26 [DEBT] — INVESTIGATED, DEFERRED
- **Why deferred:** Requires replacing `std::wstring_convert`/`std::codecvt_utf8<char32_t>` in `cpp/include/gherkin/cucumber/gherkin/utils.hpp` with a platform-independent alternative. The reporter tagged another contributor (@chybz) and said they lack sufficient knowledge. No simple drop-in replacement. Not suitable for first contribution.

### #298 — Datatable malformed without compilation error [BUG] — INVESTIGATED, DEFERRED
- **Why deferred:** Breaking change requiring cross-language consistency + new major version. Maintainer provided detailed guidance but the scope is large (all 13 parsers must produce consistent errors).

### #22 — Gherkin quietly ignores unfinished table cells [BUG] — INVESTIGATED, DEFERRED
- **Why deferred:** 304NotModified offered to work on it (Dec 2025) but never submitted. However, the scope is large: breaking change, requires cross-language parser updates, new major version needed. Maintainer explicitly said "preferably" no AI tools.

### #379 — Description parsing behaviour for Markdown changed [BUG] — INVESTIGATED, DEFERRED
- **Why deferred:** Markdown parser described by maintainer as "proof of concept bolted onto the Gherkin parser." Root cause is in `GherkinInMarkdownTokenMatcher` treating unrecognized lines as Empty. Complex parser internals.

### #28 — Pickle compiled without error from AST containing invalid example data [BUG] — INVESTIGATED, DEFERRED
- **Why deferred:** Maintainer confirmed duplicated columns are "unambiguously wrong and should result in error" but this needs cross-language consistency across all 13 implementations. Not suitable for first contribution.

### #17 — Duplicate keywords in translations [BUG] — INVESTIGATED, DEFERRED
- **Why deferred:** Marked `incomplete`. Requires major version bump. Language-specific: `ne` (Nepali), `uz` (Uzbek), `en-old`. Discussion ongoing since 2021 without resolution.

### Remaining Open Issues — SCANNED, NOT ACTIONABLE
- **#553** — Devcontainer: maintainer rejected (CI would rot, 13-language dependency hell)
- **#516** — UTF-8 BOM: maintainer said no interoperable support needed
- **#412** — cpp Windows build: partially fixed by PRs #414-#419, remaining Windows linker issue is out of scope
- **#398** — Document UTF-8: documentation lives at cucumber.io, not in this repo
- **#351** — String allocations: investigation/research issue, not a fix
- **#248** — Romanised Urdu: i18n addition marked `incomplete`
- **#246** — Syntax errors without exceptions: .NET-specific design change
- **#153** — TokenMatcher parse errors: cross-language design change
- **#136** — Feature keyword required: bug in Markdown parser, linked to Messages schema
- **#122** — Roslyn code-analysis: .NET-specific enhancement
- **#109, #100** — Markdown delimiters / Java Markdown: features, not bugs
- **#66** — Separate Gherkin/Messages dependency: architectural change
- **#54** — Max parse errors: needs cross-language consistency
- **#53** — Better testing approach: research/investigation
- **#30, #29** — Dart acceptance tests / Berp: requires Dart expertise
- **#9** — French Given invariable: language policy discussion
- **#10, #20** — Asciidoc / Markdown syntax: feature requests
- **#26** — Description indentation: feature change
- **#25** — And keyword: likely user error
- **#18** — Missing colons: maintainer said "a lot of effort, not worth it"
- **#14** — Syntax highlighters: external tooling, not parser
- **#13** — Unique test names: feature request
- **#11** — Empty scenarios: long-running discussion since 2017

## Kill List
(none)

## Priority Ranking (for PR creation)
1. **#454** — C segfault fix (qa_passed, ready for /ship)
2. **#36** — JS token acceptance tests + markdown bugfixes (code contribution, highest standing value)
3. **#515** — dotnet CONTRIBUTING.md (quick win, maintainer invited)
4. **#396** — Remove CLI from docs (quick win, maintainer confirmed)
