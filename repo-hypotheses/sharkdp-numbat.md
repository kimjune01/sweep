# Triage Graph: sharkdp/numbat

**Repo**: sharkdp/numbat  
**Stars**: 2528  
**Description**: A statically typed programming language for scientific computations with first class support for physical dimensions and units  
**Org context**: sharkdp — bat#3734 MERGED (warm org)

## Session: 2026-05-10

### Issues scanned

Total open issues: ~100

**Top candidates by activity**:
1. #218 - Mobile version (23 comments, help-wanted)
2. #4 - Use high-precision numeric type (16 comments)
3. #549 - The `|>` operator parsing errors (15 comments)
4. #536 - Notepad/soulver-like interface (14 comments)

**Recent unlabeled issues** (potential bugs):
1. #860 - [FR] AWG to mm² calculation (competing PR #825 merged)
2. #858 - [FR]: include comments when generating config ✅ **SELECTED**
3. #854 - `3.2 GHz * 6.3nm` should simplify units
4. #852 - Cannot calculate 64bit equivalent of y2k38
5. #851 - `bin(inf)` and others cause hang by infinite loop (competing PR #853 open)

**Help-wanted issues**:
- #797 - Support typographic length units
- #715 - Backslashes interfere with color codes in web interface
- #660 - Web UI font missing superscript minus symbol
- #610 - Show your Numbat programs (showcase issue)
- #360 - CI: deploy WASM version for every PR
- #282 - Relative module loading
- #269 - Add support for 'k'/'M' suffixes in integer numbers
- #218 - Mobile version

### Issue #858: Add comments to generated config

**Status**: ✅ IMPLEMENTED  
**Branch**: `fix-generate-config-comments`  
**Commit**: `0c5dbf01614accc0a85211bac151829e670225fd`

**Problem**: `numbat --generate-config` creates config.toml without explanatory comments. User requested comments matching the documentation.

**Implementation**:
- Replaced `toml::to_string(&config)` with manual format string
- Added inline comments explaining each config option
- Uses `toml::Value::String().to_string()` for proper TOML escaping
- Covers all fields: intro-banner, prompt, pretty-print, edit-mode, color, formatting section, exchange-rates section

**Review**:
- ✅ Codex: Clean implementation, correct approach
- ✅ Gemini: Perfect solution, exhaustive enum matching, safe string escaping. Suggested avoiding unnecessary `.to_string()` allocations (applied)
- ✅ Compiles successfully
- ✅ Ready for drip queue

**Drip queue**: Written to `~/.sweep/drip-queue/sharkdp-numbat.jsonl`

### Competing PRs detected

- Issue #851: PR #853 by @amogusussy (open) - Skip
- Issue #860: PR #825 (merged) - Skip

### Hypothesis testing

**H0 (Cold start)**: Warm org (sharkdp/bat#3734 merged). Expect better reception than cold orgs.

**H2 (Feature vs bug)**: Issue #858 is labeled as feature request but has clear maintainer acknowledgment ("Would be nice...Awesome application!"). Clear acceptance criteria.

**H4 (Well-scoped vs exploratory)**: Very well-scoped. Single function change, no architectural decisions needed.

**Evidence**: Issue accepted immediately by maintainer-friendly tone. Clean implementation with no rejection signals from codex or Gemini.
