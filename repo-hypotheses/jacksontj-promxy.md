# Triage Graph: jacksontj/promxy

**Timestamp**: 2026-05-09T23:00:00Z  
**Commit**: 18051df3

## Selected Issue

**#582**: release build + upload in CI  
**Status**: Actionable  
**Type**: Enhancement (CI automation)

### Why Selected

1. **Maintainer request**: jacksontj explicitly wants to offload `make release` + manual upload to CI
2. **Clear acceptance criteria**: Use softprops/action-gh-release (maintainer provided example)
3. **No competing PRs**: Zero open or closed PRs addressing CI release automation
4. **Low risk**: New workflow, doesn't modify existing code paths
5. **Immediate value**: Reduces manual toil for maintainer on every release

### Competing Issues Considered

- **#742** (zero-target logging): Already implemented in local branch, but superseded by competing PR #743
- **#732** (label_filter startup): Complex architectural question, maintainer uncertain about desired behavior
- **#713** (IPv6 fallback): Issue is in upstream prometheus/client_golang, not promxy's control
- **#697** (alertmanager CVE): Requires dependency cascade + code changes, author already hit compilation errors
- **#645** (helm chart automation): Already assigned to paulojmdias
- **#356** (remote_read test): No body, no comments, unclear requirements

## Implementation

**Branch**: `fix/582-automate-release-ci`  
**Commit**: `18051df3`

### Changes

Created `.github/workflows/release.yml`:
- Triggers on tag push (v*)
- Runs existing `make release` (build.bash script)
- Uploads all build artifacts to GitHub release
- Auto-generates release notes (maintainer already uses automated release notes per issue description)

### Why This Approach

1. **Reuses existing tooling**: No changes to build.bash or Makefile
2. **Matches maintainer workflow**: Uses softprops/action-gh-release as suggested
3. **Drop-in replacement**: Identical output to manual process (same filenames, SHA256SUMS, platform coverage)
4. **Zero breaking changes**: Existing Docker build workflow (build.yml) unaffected

## Actionability Score

**9/10**

- ✅ Maintainer explicitly requested
- ✅ Example solution provided by maintainer
- ✅ No competing PRs
- ✅ Clear acceptance criteria
- ✅ Low risk (additive change)
- ⚠️ Cannot test without pushing a tag (but workflow syntax is standard)

## Test Plan

Workflow validation will happen on:
1. PR merge → no tag, no workflow run
2. Next actual release tag push → workflow executes, uploads binaries
3. Compare GitHub release assets to previous manual releases (filename patterns, SHA256SUMS)

Manual verification before PR:
- Workflow YAML syntax valid (GitHub Actions schema)
- `make release` tested locally (already works)
- softprops/action-gh-release@v2 is current stable version
