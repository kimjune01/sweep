# Triage Graph: wild-linker/wild

Stars: 3559 | Language: Rust | Last pushed: 2026-05-12

## AI Policy
AI allowed with human in the loop. Must understand changes fully. Short PRs, one at a time.

## Contributing Policy
- Tests require Linux (clang, lld, nightly toolchain, musl target, cranelift)
- Start small, one PR at a time
- Prefer discussion before large changes

## Issues Triaged

### #1915 - Version node check for synthetic symbols [PR #1924 OPEN]
- **Type**: bug_fix (good first issue label)
- **Status**: Branch `fix/version-node-check-1915` pushed to fork; PR #1924 open, under review
- **Mechanism**: `create_dynamic_symbol_definition` in elf.rs guards version_for_symbol behind `version_count() > 0`, skipping validation when no VERSION blocks exist. Fix: also check when `version_name.is_some()`.
- **Tests**: integration test (version-node-not-found). The synthetic unit test `undefined_version_name_errors` was added in an earlier revision and removed at marxin's request (commit dd44e566).
- **Risk**: Low. Change is narrowly scoped to one guard condition. Existing tests all pass.
- **Previous attempt**: gate_fail (overly broad check that would break versioned-script-symbol test). Fixed in this version.
- **Competing PRs**: None

#### CI Failure Hypothesis Graph (PR #1924, run 25723823692)
| H | claim | evidence | verdict |
|---|---|---|---|
| H_a | failure is regression caused by fix | only fmt diff, no test/compile errors | falsified |
| H_b | failure is pre-existing flake | test commit added the lines flagged | falsified |
| H_c | fix is incomplete / cosmetic gap | nightly rustfmt wrapped 2 multi-arg `assert!` lines >100c at version_script.rs:1189,1201; stable rustfmt didn't enforce it locally | confirmed |

- **Resolution**: commit e9905ebf "style: apply rustfmt to test assertions". Single file, +8/-2. Verified via `cargo +nightly fmt --all -- --check` (clean) and `cargo test -p libwild version_script`.

#### Review feedback (2026-05-13/14)
- **davidlattimore (maintainer)**: hypothesis-table reply read as bot output. Asked for human-written communication going forward. Repo added to `~/.sweep/human-only.txt` — pipeline now routes all wild PR comments to the human punch list. Plain-prose reply posted at #issuecomment-4453627091.
- **marxin (collaborator)**: requested removal of the synthetic `undefined_version_name_errors` unit test; only the integration test remains. Resolved in commit dd44e566.

## Issues Evaluated but Not Selected

### #1909 - PROVIDE/PROVIDE_HIDDEN support
- Feature, not a bug fix. Complex linker script semantics.

### #1905 - LTO poppler build failure
- Complex LTO issue, hard to reproduce.

### #1868 - .eh_frame 32-bit offset overflow
- Requires large binary reproduction environment.

### #1769 - ALIGNOF/LOADADDR functions
- Being actively worked by plasmaDestroyer (contributor).
