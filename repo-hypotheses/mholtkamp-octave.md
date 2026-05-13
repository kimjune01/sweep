# mholtkamp/octave Triage Graph

**Repo**: mholtkamp/octave (496★, C++ game engine)  
**Status**: Development hiatus, PRs welcomed but may not merge soon  
**Date**: 2026-05-11

## Issues Investigated

### ✅ #61 - Signedness comparison warnings during build
- **Status**: Fixed, queued for drip
- **Branch**: `fix-signedness-warnings-issue61`
- **Maintainer guidance**: Cast `size()` to `int32_t` (explicit preference stated)
- **Fix**: Applied maintainer's preferred pattern to Scene.cpp lines 354, 356
- **Standing strategy**: Minimal, safe fix following explicit direction
- **Commit**: 98ba87c92a41e3de7357fa79858f4ab60f681651
- **Diff**: 2 insertions, 2 deletions in 1 file

### ✅ #68 - Shader compiler linux script appears to have DOS line breaks
- **Status**: Fixed, queued for drip
- **Branch**: `fix-dos-line-endings-issue68`
- **Root cause**: Git autocrlf conversion and ZIP download CRLF injection
- **Fix**: Added `.gitattributes` with `*.sh text eol=lf`
- **Maintainer acknowledged**: "I'll try to fix it asap"
- **Commit**: 6675f820dfb96a2a3bc829f78c2dd4d1878d56a2
- **Diff**: 2 insertions, 0 deletions in 1 file (new)

### ⚠️ #23 - Add spirv_cross to dependencies
- **Status**: Skipped - unclear/potentially invalid
- **Analysis**: spirv_cross already vendored in `External/Android/spirv_cross/`
- **Complication**: Linux builds use `libspirv-cross-core.a` from Vulkan SDK
- **Issue**: Reported Oct 2024, no maintainer response, unclear reproduction
- **Decision**: Insufficient clarity for first PR

### ⚠️ #47 - Error when creating New Project after deleting root node
- **Status**: Skipped - requires editor testing
- **Analysis**: Found CreateNewProject in ActionManager.cpp:1453
- **Blocker**: Cannot reproduce without running editor, screenshot insufficient
- **Decision**: Not suitable for first PR without test environment

### ⚠️ #20 - Engine is case-sensitive while Windows is not
- **Status**: Skipped - architectural complexity
- **Analysis**: Filesystem collision on case-insensitive Windows
- **Scope**: Asset management system refactor required
- **Decision**: Too complex for standing-building PR

## Quality Gates Applied

1. **Devil's advocate review** - Each fix challenged for safety and scope
2. **Maintainer alignment** - #61 follows explicit pattern, #68 addresses acknowledged bug
3. **Minimal scope** - Only fix reported issue, no scope creep
4. **Self-review** - Verified casts are safe for game engine node counts

## Competing PRs

Checked all open/closed PRs - no competing work on #61, #68, #23, #47, #20.

## Next Steps

1. Wait for drip advancement
2. Monitor #61 and #68 for maintainer feedback
3. If these merge, expand to similar signedness warnings across codebase
