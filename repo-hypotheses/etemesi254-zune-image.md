# Triage Graph: etemesi254/zune-image

## MAINTAINER PREFERENCES

- No CONTRIBUTING.md found
- Default Rust project conventions apply
- Target branch: main
- Test-driven development expected (from issue discussion)

## ISSUES INVESTIGATED

### Issue #385: Newline in errors ✅ QUEUED

**Status**: QUEUED (branch: fix-385-remove-newlines-in-errors)  
**Created**: 2026-04-30  
**Last Updated**: 2026-05-01

**Description**: Error Display/Debug implementations use writeln! which adds trailing newlines. This breaks logging when using tracing library instrumentation. The maintainer acknowledged the issue and requested changing all crates from writeln! to write!.

**Bug Hunt Analysis**:
1. Existing mechanism: All error types in zune-inflate, zune-png, zune-qoi, zune-psd, and zune-image use writeln! in fmt() implementations
2. Why current code does it: Likely copied pattern without considering consumer needs
3. Wrong fix would be: Only fixing one crate, or fixing Display but not Debug
4. Devil's advocate: "This isn't a bug because it's consistent" - REJECTED. The maintainer explicitly agreed this violates Rust conventions per thiserror precedent.

**Implementation**:
- TDD Phase 1: Created error_formatting.rs test that validates no trailing newlines (test fails on main) ✅
- TDD Phase 2: Changed writeln! to write! across 5 error files ✅
- All tests pass ✅
- 2 commits: test first, then fix

**Evidence**: Maintainer-acknowledged, contributor said they'd do it but didn't after 10 days, clear mechanical fix.

## ISSUES REJECTED

### Issue #362: zune-jpeg range panic ❌ TEST_PASSES_ON_MASTER

Fuzz-found panic in idct/scalar.rs. Test with provided sample passes on main - likely already fixed silently. No recent commits reference this issue. Not worth investigating further.

### Issue #361: AVX2 unwrap panic ⏸️ PARTIAL_FIX

Maintainer added stopgaps in 0.5.13 but said "haven't fixed it to my satisfaction". Issue still open but requires deep AVX2/IDCT knowledge. Not a good first contribution.

### Issue #372: APNG blending artifacts ⏸️ SPEC_AMBIGUITY

Maintainer is stuck between two test cases that behave differently under APNG spec. They've done deep analysis and are unsure what the correct behavior is. Requires spec expertise, not a good first contribution.

## HYPOTHESIS TRACKING

- **H0 (Bug fixes merge)**: Issue #385 is a maintainer-requested fix with clear acceptance criteria
- **H2 (Solo maintainer, docs/error messages)**: This is an error message improvement on a 475-star repo
- **First contribution strategy**: Chose smallest mechanical fix with maintainer blessing. Standing before ambition.
