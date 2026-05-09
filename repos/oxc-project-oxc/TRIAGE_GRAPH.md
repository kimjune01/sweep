# Triage Graph: oxc-project/oxc

**Hypothesis:** H1/H6 — umbrella lint-rule-port issues, Rust, external-merge-daily, 21K stars. Fills H6 (structured test/verification) gap in roster.

**Date:** 2026-05-09

## Repository profile

- **Stars:** 21K
- **Language:** Rust
- **Maintainer response:** External, daily merges
- **Issue structure:** Umbrella tracking issues for lint rule ports (H6 pattern)
- **Existing PRs by us:** None

## Issue scan (100 issues, fresh to stale)

### Selected for implementation: #22230

**Title:** linter: rule options are dropped from `--print-config` when using object-form `extends` in `oxlint.config.ts`

**Type:** Bug fix

**Mechanical acceptance criterion:** 
- `--print-config` must output rule options from extended configs
- Test: config with `extends: [baseConfig]` where `baseConfig` has `"getter-return": ["error", { "allowImplicit": true }]` must print options array, not just severity

**Why selected:**
1. **High-quality bug report** — includes repro steps, root cause analysis with file/line references, and suggested fix directions
2. **Self-contained** — fix requires only config builder changes, no external dependencies
3. **0 comments** — fresh issue (2026-05-07), no competing activity
4. **No competing PRs** — searched for "22230 OR print-config", found only unrelated PRs
5. **Clear scope** — runtime linting is unaffected, bug is isolated to `--print-config` output path
6. **Fills H1 (bug fix with clear repro)** — roster priority

**Root cause (from issue reporter):**
`ConfigStoreBuilder::resolve_final_config_file` (line 562) zips severities from `self.rules` (merged state) with options from the `oxlintrc` parameter (un-merged root config passed from `lint.rs:303`). Rules from `extends` exist in merged config but not in the lookup table, so `unwrap_or_default()` returns empty options.

**Implementation:**
- Added `merged_oxlintrc: Option<Oxlintrc>` field to `ConfigStoreBuilder`
- Stored merged config (from `resolve_oxlintrc_config` line 204) in `from_oxlintrc`
- Used merged config in `resolve_final_config_file` via `self.merged_oxlintrc.clone().unwrap_or(oxlintrc)`
- Added test fixture `print_config_extends_with_options` with object-form extends and rule options

**Commit:** `fix/print-config-extends-options` at 17e703a310

**Queued for drip:** Yes

## Other candidates considered

### #22269 - Oxlint panics on absolute path
- **Type:** Bug (panic on absolute lint target path)
- **Status:** Competing PR #20101 open since 2026-03-07, changes requested (needs test), stale
- **Skip reason:** Duplicate effort, existing PR needs rescue not replacement

### #22160 - vitest/require-hook false positive
- **Type:** Bug (false positive on Vue/JSX files)
- **Status:** 0 comments, fresh (2026-05-05)
- **Skip reason:** Lower priority than #22230 (less mechanical acceptance criterion, requires understanding rule logic)

### #1141 - jsx-a11y umbrella
- **Type:** Feature (lint rule ports)
- **Status:** labeled "good first issue", 2/31 remaining
- **Skip reason:** Features don't merge at cold repos until 3+ bug fix merges establish trust

## Hypothesis validation

**H6 (structured test/verification):** ✅ Confirmed
- Umbrella issues (#1141, #492, #1170, #2180) track lint rule ports with checklists
- `just new-jsx-a11y-rule <NAME>` scaffolds test fixtures
- Clear acceptance: all ESLint plugin tests must pass

**H1 (bug fix, clear repro):** ✅ Selected #22230
- Root cause analysis in issue
- Minimal fix (3 fields, 20 lines)
- Test fixture demonstrates bug + fix

**Merge velocity:** External, daily
- Last 10 PRs merged same-day or next-day
- #22271 (linter fix) merged 2026-05-09 (same day as issue)
- #22246 (transformer panic) merged 2026-05-08 (1 day)

## Next steps

1. ✅ Implementation complete
2. ✅ Branch queued for drip
3. Wait for CI to generate test snapshot
4. If snapshot passes, push to fork and open PR
5. If maintainers request changes, apply and re-push (don't close)

## Lessons

- **Object-form extends in TypeScript configs** is a real use case, not edge case
- Issue #22230 demonstrates ideal bug report: repro + root cause + fix directions
- Rust codebases with generated code (rule_runner_impls.rs, rules_enum.rs) need care during local testing
- Test fixtures in `apps/oxlint/test/fixtures/` auto-discovered by e2e.test.ts
