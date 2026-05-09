# anchore/syft Triage Graph

**Repository**: anchore/syft  
**Language**: Go  
**Hypothesis**: H0/H3 — good-first-issues, 1h external merge times, DCO sign-off required  
**Triage Date**: 2026-05-09

## Issue Scan Summary

**Total issues scanned**: 20 bugs  
**Actionable issues found**: 1  
**Competing PRs eliminated**: 15  
**Selected issue**: #4760

## Issue Evaluation

### ✅ Selected: #4760 - OS package (deb) components duplicated as pypi components

**Status**: Maintainer-acknowledged, design direction provided  
**Competing PRs**: None  
**Actionability**: High  

**Maintainer comments**:
- kzantow provided clear design direction: add config options per distro-cataloger + top-level flag
- User requested assignment 2026-04-20, but no PR submitted
- Related to existing `exclude-binary-overlap-by-ownership` feature

**Implementation**:
- Added `ExcludeLanguageOverlapByOwnership` config option (default: false)
- Mirrors existing binary overlap exclusion pattern
- Filters language packages (Python, NPM, Ruby, etc.) when owned by OS packages
- Includes unit tests and validation

**Branch**: fix/exclude-language-overlap-4760  
**Commit**: 7f2a5a17  
**Tests**: PASS (all relationship and options tests)

### ❌ Rejected Issues

#### #4867, #4820 - Binary version support (julia, helm)
- **Reason**: Competing PRs from tjhub1983

#### #4866, #4865 - Binary version support (go s390, deno)
- **Reason**: Competing PRs from tjhub1983

#### #4796 - Go 1.26 fs.DirEntry compatibility
- **Reason**: Competing PR #4802 from joaquinhuigomez

#### #4721 - Compressed kernel modules
- **Reason**: Two competing PRs (#4740, #4849)

#### #4712 - Wrong CPE for libpcap
- **Reason**: Two competing PRs (#4854, #4787)

#### #4653 - Incorrect CPE for React
- **Reason**: Two competing PRs (#4682, #4783)

#### #4816 - Chisel duplicate entries
- **Reason**: User-resolved, maintainer says will close when #3824 implemented

#### #4604 - ELF notes for dynamically loaded libraries
- **Reason**: Vague, more feature request than bug fix

## Hypothesis Validation

**H0 (Good First Issues)**: ✅ CONFIRMED
- 57 issues tagged `good first issue`
- Clear labeling for newcomers

**H3 (Fast External Merges)**: ⚠️ PARTIAL
- Many competing PRs from external contributors
- PRs exist but unclear merge speed (need PR history analysis)

**DCO Sign-off**: ✅ CONFIRMED
- Required for all commits
- Must use `git commit -s`

## Repository Health

**Strengths**:
- Active maintainer engagement (kzantow)
- Clear issue labeling
- Good test coverage required

**Concerns**:
- High competing PR density on issues
- Some PRs appear stale (need aging analysis)

## Next Steps

1. ✅ Implementation complete
2. ✅ Tests passing
3. ✅ DCO sign-off applied
4. ✅ Branch queued in drip
5. ⏳ Await merge or stale PRs to clear

## Files Changed

- `cmd/syft/internal/options/catalog.go` - Add config to relationships
- `cmd/syft/internal/options/pkg.go` - Add language overlap config
- `internal/relationship/exclude_language_packages_by_file_ownership_overlap.go` - New filtering logic
- `internal/relationship/exclude_language_packages_by_file_ownership_overlap_test.go` - Unit tests
- `internal/task/relationship_tasks.go` - Wire up new filter
- `syft/cataloging/relationships.go` - Add config field and builder method

## Test Coverage

```
go test ./internal/relationship/...
ok  	github.com/anchore/syft/internal/relationship	0.322s
ok  	github.com/anchore/syft/internal/relationship/binary	0.512s

go test ./cmd/syft/internal/options/...
ok  	github.com/anchore/syft/cmd/syft/internal/options	0.810s
```
