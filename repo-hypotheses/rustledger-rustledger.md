# Triage Graph: rustledger/rustledger

**Repo**: rustledger/rustledger (242 stars, 5 open issues)  
**Triage date**: 2026-05-11  
**Agent**: kimjune01 bot

## Summary

- **Addressed**: 1 issue (#1088)
- **Skipped**: 1 issue (#923)
- **Denied**: 0 issues

## Addressed Issues

### #1088 — ci: Gitleaks Secret Scan fails on every PR (missing GITLEAKS_LICENSE)

**Type**: CI fix  
**Branch**: `fix/gitleaks-license-requirement`  
**Status**: queued (ready for drip)  
**Commit**: b48d74e44a5aabf303f4146c5da8f08f6aed8d0a

**Problem**: The `gitleaks-action@v2` started requiring a paid license for org repos. The workflow passes `GITLEAKS_LICENSE: ${{ secrets.GITLEAKS_LICENSE }}` but the secret isn't set, causing every PR to fail the security check.

**Solution**: Swapped the GitHub Action for the standalone gitleaks binary (v8.21.2), which remains free. The fix:
- Downloads the binary at workflow runtime
- Uses the same `.gitleaks.toml` config
- Passes identical flags (`--config`, `--source`, `--verbose`, `--redact`)
- No license required

**Tested**: Locally on darwin_arm64 against 2218 commits. Workflow will use linux_x64 on ubuntu-latest runner.

**Evidence trajectory**: Direct bug fix. The issue description already diagnosed the root cause (licensing change) and proposed the correct fix (swap to standalone binary). Implementation was straightforward — replaced 6 lines of YAML with a 3-line shell script that downloads and runs the binary.

## Skipped Issues

### #923 — [Feature]: IBKR Importer

**Type**: Feature request  
**Reason**: Substantial multi-phase feature that maintainer (@robcohen) already committed to implementing ("Will do this week" on 2026-04-29). Features don't merge at cold repos — bug fixes do. Also, repo has only 5 open issues and is very actively maintained (10 PRs merged in the last 24 hours), so maintainer bandwidth is not constrained. Opening a competing implementation would waste effort.

**Maintainer commitment**: robcohen maintains ibflex2 (the Python Flex parser) and offered to pair on the implementation. This is a domain-expert feature, not a good fit for external contribution at this stage.

## Hypothesis Updates

**H0 (bug fixes merge, features don't)**: Confirmed. #1088 is a clear CI bug fix — red X on every PR, zero value delivered, obvious root cause. This is the sweet spot for cold repo contributions.

**H1 (200-500 star bucket = 77% fix rate)**: Rustledger is at 242 stars, but only has 5 open issues. The usual "solo maintainer, backlog of boring fixes" pattern doesn't apply here — the maintainer is extremely active and the issue queue is intentionally small. The repo is well-maintained, not under-maintained.

**H5 (domain expertise matters for features)**: #923 reinforces this. The maintainer maintains the upstream Python parser and has deep domain knowledge of IBKR Flex semantics. External contributors attempting this feature would need to learn the Flex XML schema, the existing `Importer` trait, and the rustledger posting model — all to deliver something the maintainer can do faster and better.

## Denylist

None. No issues denied.

## Notes

- CONTRIBUTING.md is comprehensive: conventional commits, branch naming (`fix/`, `feature/`, etc.), plugin testing requirements with mutation testing floor (≤10% survival rate), and a detailed release process.
- Repo uses GitHub Flow (feature branches → main, no develop branch).
- CI includes cargo-deny, cargo-vet, dependency-review, SBOM generation, and (now-fixed) gitleaks scanning.
- robcohen has merged 10 PRs in the last 24 hours, all perf/fix/chore. Very responsive maintainer.
