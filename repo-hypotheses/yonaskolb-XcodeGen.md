# Triage Graph: yonaskolb/XcodeGen

## Repo Context
- Default branch: master
- Language: Swift (SPM)
- CONTRIBUTING.md: run tests (`swift test`), add changelog entry, include PR number, commit TestProject fixture diffs
- AGENTS.md: none
- Anti-AI policy: none detected
- Maintainer: @yonaskolb (active, responds to issues/PRs)

## Triaged Issues

### #1032 — .DS_Store files in cache [BUG] ✅ IMPLEMENTED
- **Status**: triaged, branch pushed
- **Branch**: `fix/ds-store-cache-invalidation`
- **Maintainer signal**: yonaskolb confirmed bug, explicitly invited PR
- **Label**: `bug`
- **Fix**: Filter `.DS_Store` and `.orig` files from `allTrackedFiles` in `Project.swift`, matching `SourceGenerator`'s existing exclusions
- **Test**: Added `testAllTrackedFilesExcludesIgnoredFiles` in `ProjectSpecTests.swift`
- **Risk**: Low — additive filter, no behavioral change to project generation
- **Competing PRs**: None

## Evaluated but Not Triaged

### #1527 — dead "struct" link in README
- **Type**: doc fix
- **Reason skipped**: Too trivial for pipeline standing. No maintainer signal.

### #1549 — Missing package product when adding local package
- **Type**: bug (XCSwiftPackageProductDependency missing `package` backlink for local packages)
- **Reason deferred**: Complex fix touching PBX generation. Good candidate for second contribution after #1032 merges.
- **Root cause**: Known — local package branch of dependency emitter skips `package = <refId>` that remote branch sets. Detailed in #1549 comment by magnetarai-founder.

### #1551 — parallelizable scheme parameter doesn't disable parallel testing
- **Reason skipped**: PR #1565 already merged mapping `parallelizable: true` to "all". Residual issue may be an Xcode behavior change, not clearly actionable.

### #1553 — Swift 6.0 to 6.1 disables upcoming features
- **Reason skipped**: Likely Xcode/Swift toolchain behavior change, not an XcodeGen bug. No maintainer response.

### #1585 — Package traits
- **Type**: feature request
- **Reason skipped**: Feature, not bug fix. Needs standing first per pipeline rules.

### #1615 — folder resources use bare name instead of relative path
- **Type**: bug
- **Reason deferred**: No maintainer response, no minimal repro provided.

## Denied Issues
(none)
