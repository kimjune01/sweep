# Triage Graph: hudson-trading/slang-server

**Repository**: hudson-trading/slang-server (219★, C++ — SystemVerilog LSP)  
**Triage Date**: 2026-05-11  
**Open Issues**: 27 (from gh API, only 1 returned in filtered query, actual count ~15 non-upstream)

## Denylist

### Already Fixed / In Progress
- **#310**: Incorrect Hover Markdown for Backticks — **FIXED** in branch `fix-backtick-hover-markdown`
- **#322**: DPI highlights — **HAS COMPETING PR #337** by @nahomar
- **#270**: System task hover information — **HAS COMPETING PR #339** by @nahomar

### Upstream Issues (Slang Library)
- **#197**: Only first character underlined for redefined variable diagnostic
- **#300**: Slang fails nested token-paste macro expansion in parameterized macro

### Low Priority / Workarounds Exist
- **#327**: CTRE bundled with reflect-cpp — contributor says "best to leave it be"
- **#319**: Build fail with gcc 15 — false positive, workaround: `-DCMAKE_CXX_FLAGS="-Wno-maybe-uninitialized"`
- **#316**: Generate filelist feature request — workaround: use `slang --all-deps`

### Large Features (Not Standing-Building)
- **#268**: Implement Semantic Tokens — PR #288 exists but stalled
- **#301**: Quick fix imports — medium scope feature
- **#206**: Automatic top/buildfile saving — medium scope, design discussion ongoing
- **#305**, **#306**: Wave viewer integration features
- **#135**: UVM support — requires pre-compiled headers + request cancellation

### Neovim-Specific (Requires Lua)
- **#248**: Hierarchy options like in VSCode — clear spec from @sgaulter, but requires Neovim client work

## Hypothesis Testing

### H0: Maintainer responsiveness
**SUPPORTED**. AndrewNolte (@AndrewNolte, COLLABORATOR) and @sgaulter (COLLABORATOR) are highly active. Response times: <24h on most issues. @evanwporter (CONTRIBUTOR) is also very active with detailed technical proposals.

### H1: Test coverage expectations
**PARTIAL**. Tests exist in `tests/cpp/`, including HoverTests.cpp and MarkupTests.cpp. CONTRIBUTING.md states: "New changes will almost always require corresponding unit tests". However, many tests check for content presence, not exact formatting.

### H2: Code style requirements
**CLEAR**. CONTRIBUTING.md specifies:
- Based on LLVM Coding Standards with exceptions
- Column width: 100
- lowerCase for functions/params/locals (not UpperCase)
- `#pragma once` (not header guards)
- Must pass clang-format and pre-commit checks
- Use CMakePresets.json for high warning levels

### H3: Contribution workflow
**STANDARD**. No CLA, no commit limits mentioned. Recommends opening discussion before large PRs. Build system: CMake + submodules (slang, reflect-cpp, ctre).

### H4: Domain barriers
**MODERATE**. SystemVerilog LSP requires understanding:
- Language Server Protocol (LSP)
- SystemVerilog syntax nuances (macros, token-paste operators)
- Markdown rendering edge cases
- C++ template metaprogramming (reflect-cpp, fmt)

### H5: Standing-building path
**BUG FIXES FIRST**. Issues like #310 (backtick rendering) are excellent standing-builders:
- Clear mechanical fix identified by maintainer/contributor
- Low risk
- Improves real user pain points
- Demonstrates attention to detail

Feature requests like #316, #206 require more design discussion and are better tackled after establishing standing via bug fixes.

### H6: Community dynamics
**COLLABORATIVE**. @evanwporter proposes fixes and volunteers for future work. @maz9-prog offers to implement #248. Maintainers provide clear guidance and appreciate contributions. No signs of hostility or bikeshedding.

## Actionable Issues (Post-#310)

After fixing #310, potential next targets:

1. **#248**: Neovim hierarchy options — **IF** you know Lua/Neovim plugin dev. Clear spec from maintainer.
2. **Documentation improvements**: The docs exist but may have gaps. Check for missing examples or unclear sections.
3. **Test coverage**: Add tests for edge cases in existing features (e.g., markdown rendering with various backtick counts).

## Evidence
- 27 open issues scanned
- 12 open PRs scanned  
- CONTRIBUTING.md, DEVELOPING.md, CLAUDE.md reviewed
- Active branches: 100+ AndrewNolte/stack/* branches (likely stacked PR workflow)
- CI: GitHub Actions with gcc/clang builds
- Submodules: slang (SystemVerilog compiler), reflect-cpp (JSON), ctre (regex)
