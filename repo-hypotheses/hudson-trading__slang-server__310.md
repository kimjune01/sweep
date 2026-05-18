# Hypothesis Graph: hudson-trading/slang-server#310

**Issue**: Incorrect Hover Markdown for Backticks (reporter: henry-hsieh)
**PR**: #342 — `kimjune01:fix-backtick-hover-markdown` (open, no reviews)
**Investigation date**: 2026-05-17

## H₀ — Hover markdown rendering breaks on SystemVerilog content containing backticks

- **Observation**: Hover content like `` `define MACRO_A 10 `` or `` `define JOIN_MACRO(name) name```MACRO_A `` is wrapped with single backticks by `Paragraph::appendCode()` in `src/util/Markdown.cpp:54`. Per CommonMark, a code-span delimiter run must not appear inside the content, so any single backtick in content breaks the span.
- **Perturbation**: Read `Markdown.cpp:53` on master. Confirmed: `fmt::format_to(..., "`{}`", code)`.
- **Trajectory**: Divergent — confirmed.
- **Reasoning mode**: Deduction (code read). Confidence: 98%.
- **Provenance**: Maintainer @evanwporter pointed at exactly `Markdown.cpp:54` in the issue thread and said "just need to surround single line code hovers with double backticks." Reporter @henry-hsieh requested 4-backtick padding to handle the `name```MACRO_A` case.

## H₁ — Static double-backtick wrap fixes the reported case but not all valid SV

- **Hypothesis**: Maintainer's suggestion (always wrap with `` `` … `` ``) works for the two reported examples and is the minimal patch.
- **Perturbation**: Apply CommonMark rule. A 2-backtick delimiter closes on the next *exact* 2-backtick run. The triple-backtick case (3 consecutive) does not match a 2-backtick run, so double-backticks survive it.
- **Kill condition**: SystemVerilog has a `` `` `` token-paste operator (two backticks). Macros like `` `define CAT(a,b) a``b `` produce hover content with *exactly two* consecutive backticks — which would terminate a 2-backtick wrapper mid-content.
- **Trajectory**: Oscillatory — works for reported cases, fails for valid adjacent case.
- **Edge**: Need delimiter sized to the longest backtick run in content. (Split into H₂.)
- **Reasoning mode**: Deduction. Confidence: 92%.

## H₂ — Dynamic delimiter (N+1 backticks where N is longest run) covers all SV cases

- **Hypothesis**: Scan content for max consecutive-backtick run N; wrap with N+1 backticks; pad with one space on each side when N≥1 (so adjacent-backtick content doesn't extend the delimiter run).
- **Perturbation**: Read the PR diff. `appendCode` does exactly this:
  ```cpp
  size_t maxBackticks = …scan…;
  size_t delimiterCount = maxBackticks + 1;
  bool needsSpaces = maxBackticks > 0;
  ```
- **Trajectory**: Divergent — confirmed for all currently-emitted SV constructs (1, 2, 3 consecutive backticks).
- **Reasoning mode**: Deduction (code read + CommonMark spec). Confidence: 95%.

### Provenance check
- Origin: `Markdown.cpp:54` was introduced as part of the clangd-style hover refactor (PR #190 merged 2026-01-06, author AndrewNolte). The single-backtick wrap was a migration default, not a deliberately defended choice — supports the fix.
- Adjacent work: Issue #310's other concern (backticks in comments) is being separately handled — PR #317 (evanwporter, merged) added a plaintext-hover option. The remaining work — fix the inline-code wrap — is what #342 addresses. No duplicate PR.
- CommonMark space-stripping: a code span with leading AND trailing space (and non-space content) has exactly one space stripped from each side. The PR's unconditional padding is safe for all content not composed entirely of spaces — fine in practice.

## H₃ — Fail-on-master / pass-on-fix for the added tests

- **Hypothesis**: Of the three new tests in `MarkupTests.cpp`, two genuinely attest the fix.
- **Perturbation**: Mentally apply master's `` `{}` `` to each test input.
  - `AppendCode_BacktickWrapping`: input `` `define MACRO_A 10 ``. Master output `` ``define MACRO_A 10` ``. Expected `` `` `define MACRO_A 10 `` ``. **Fails on master**, passes on fix. ✓
  - `AppendCode_TripleBacktickTokenPaste`: input has `` ``` ``. Master output wraps with single backticks, mismatched. **Fails on master**, passes on fix. ✓
  - `AppendCode_NoBackticks`: input `int variable = 42`. Master output `` `int variable = 42` ``. **Passes on master** (no backticks to scan; delimiterCount=1, no padding). Regression-coverage only, not bug attestation — acceptable.
- **Trajectory**: Divergent — confirmed.
- **Reasoning mode**: Deduction. Confidence: 97%.

## H₄ — PR description drift

- **Observation**: PR body claims "switches appendCode() to use double-backtick wrapping." Actual implementation is dynamic-delimiter, strictly more correct.
- **Kill condition**: Maintainer reads the body and rejects on accuracy grounds (low risk — code review will reveal the actual change).
- **Edge**: Splice the description to match the implementation. Amend is low-risk (no notification).
- **Trajectory**: Divergent — confirmed.
- **Reasoning mode**: Deduction. Confidence: 99%.

## Graph state

| Node | Status | Mode | Confidence |
|------|--------|------|------------|
| H₀: single-backtick wrap breaks rendering | Confirmed | Deduction | 98% |
| H₁: maintainer's static double-backtick fix | Killed (oscillatory; misses `` `` operator) | Deduction | 92% |
| H₂: dynamic delimiter | Confirmed | Deduction | 95% |
| H₃: tests fail-on-master / pass-on-fix | Confirmed (2 of 3 attest; 1 is regression coverage) | Deduction | 97% |
| H₄: PR body says "double-backtick" but code is dynamic | Confirmed | Deduction | 99% |

## Frontier

- None on the diagnosis side. Fix is structurally correct and minimally scoped to `appendCode`.
- Maintainer comment hint: "the debug hover headers which iirc are in slang server.cpp or server driver." All emission paths route through `appendCode` (verified: `ShallowAnalysis.cpp:549,576,589` + `Hovers.cpp` calls). The single-point fix covers the debug hover headers too — no extra change required.

## Causal chain

`Markdown.cpp:54` wraps with `` `{}` `` → SV content frequently contains backticks (preprocessor directives, token-paste) → CommonMark code-span delimiter rule violated → hover markdown renders garbage → fix wraps with N+1 backticks (N = longest run in content) + space padding when N≥1.

## Recommendation

1. Edit PR body to describe the actual implementation (dynamic delimiter, not "double-backtick").
2. No code changes needed. PR is ready for review.
3. No new PR — update the existing one.
