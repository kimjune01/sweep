# Triage Graph: EmbarkStudios/cargo-deny

Session: 2026-05-10
First contribution to repo.

## Denylist

### Covered by existing PRs
- #827 - allow `or` combinations in allow list (covered by PR #853)
- #850 - optional ban for prereleases (covered by PR #852)

### Maintainer explicitly not interested
- #831 - GitHub output format (maintainer: "I have no interest in doing this")
- #796 - notice level for bans (maintainer doesn't see the value)
- #820 - SARIF report issues (maintainer: "I don't care about SARIF at all")

### Too complex for first contribution
- #856 - generate third-party licenses file (maintainer wants to merge with cargo-about)
- #770 - large-scale bans maintenance (needs design discussion)
- #849 - transitive duplicate ignoring (complex feature)

## Completed

1. **#854** - DONE: Fix advisory-db git operations affected by parent git context
   - Branch: fix/854-git-env-isolation
   - Commit: 5518d56
   - Fixed git env var isolation (8 vars) + capture() error handling bug
   - Reviews: codex (caught error handling bug, suggested complete env list), gemini (confirmed logic, suggested GIT_QUARANTINE_PATH)
   - Status: committed, awaiting drip

## Priority candidates (smallest bugs first)

2. **#792** - Bug: cargo-deny combines features from all workspace crates
   - Bug, no comments, feature handling issue
   
3. **#783** - Bug: skip-tree skips more crates than expected
   - Bug, no comments, scoping issue

4. **#772** - Bug: unused workspace dependency false positive with graph exclude
   - Bug, no comments, false positive

5. **#765** - Bug: build-script error doesn't show computed hash
   - Bug, error message quality issue
   - Has one comment with repro case
