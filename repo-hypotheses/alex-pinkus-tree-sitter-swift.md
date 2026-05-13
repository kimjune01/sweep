# Triage Graph: alex-pinkus/tree-sitter-swift

Repository: alex-pinkus/tree-sitter-swift (209 stars, 31 open issues)
Triage Date: 2026-05-11
Type: Tree-sitter grammar for Swift

## Summary

Triaged 5 issues, implemented fixes for 2, skipped 3 due to complexity.

### Implemented (2)

#### #550: `class` with `nonisolated(unsafe)` member is parsed into ERROR
- **Status**: Fixed
- **Branch**: fix-550-nonisolated-unsafe  
- **Type**: Grammar bug - missing modifier support
- **Fix**: Added `nonisolated(unsafe)` to member_modifier choices in grammar.js
- **Test**: Added corpus test in test/corpus/classes.txt
- **Impact**: Fixes class symbol extraction for Swift 5.9+ code using nonisolated(unsafe)

#### #509: Support raw identifiers (added in Swift 6.2)
- **Status**: Fixed
- **Branch**: fix-509-raw-identifiers
- **Type**: Missing language feature (SE-0451)
- **Fix**: Updated simple_identifier regex from `/`[^\r\n` ]*`/` to `/`[^\r\n`]*`/` to allow spaces
- **Test**: Added corpus test in test/corpus/functions.txt
- **Impact**: Enables parsing of test function names with spaces like @Test func `square returns x * x`()

### Skipped (3)

#### #513: a.b * d(e.f) * g.h.i.j parsed incorrectly
- **Status**: Deferred
- **Reason**: Requires complex precedence restructuring. Attempted fix (raising call/navigation precedence) caused 22 test failures.
- **Root cause**: Call expressions and navigation expressions have precedence -2 and -1, lower than multiplication (11). Changing this creates ambiguity with if-statements and trailing closures.
- **Next steps**: Requires either external scanner changes or grammar restructuring beyond triage scope.

#### #396: Generic types are recognized as `comparison_expression`
- **Status**: Deferred
- **Reason**: Fundamental ambiguity in Swift grammar. `Response<MyData>.self` parsed as `Response < MyData > .self` (comparisons) instead of generic type.
- **Root cause**: Parser cannot distinguish `<` as type argument start vs comparison operator without lookahead. Tree-sitter's GLR can handle this but requires external scanner support for `<`/`>` or significant grammar restructuring.
- **Next steps**: Requires external scanner modifications (src/scanner.c) to handle generic type context.

#### #153: Binary expressions with function calls on their RHS get incorrectly parsed
- **Status**: Not attempted (similar to #513)
- **Reason**: Operator precedence issue related to #513. `if x && y && z.def()` parses incorrectly.

## Scoring Methodology

- **High priority**: Parsing bugs with ERROR nodes, clear reproduction, recent Swift features
- **Medium priority**: Incorrect AST structure without ERROR, older issues with community interest  
- **Low priority**: Documentation, tooling setup, build system issues

## Repo Characteristics

- **Maintainer**: alex-pinkus (responsive, merged 3 PRs in past week)
- **Contribution policy**: No generated files (parser.c) in repo, use npm install && npm test
- **Test structure**: Corpus tests in test/corpus/*.txt with input/expected AST pairs
- **Grammar complexity**: 2000+ lines, external scanner for context-sensitive operators

## Denied Issues

None yet.

## Notes

Tree-sitter-swift has unique policy: parser.c is not checked in. Contributors must run `npx tree-sitter generate` locally. This reduces diff noise but requires tree-sitter CLI setup.

Grammar uses precedence values from -4 to 13, with negative values for constructs that defer to context (if, lambda, try, etc.) and positive values for binary operators. Precedence changes require careful testing as they cascade through expression parsing.
