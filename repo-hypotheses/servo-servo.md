# Triage Graph: servo/servo

Generated: 2026-05-10

## Repo Profile

- **Stars:** 30K+
- **Language:** Rust
- **Domain:** Browser engine (web rendering)
- **Maintainers:** mrobinson, jdm, mukilan, nicol (igalia team)
- **Review culture:** Well-structured. Meta-issues track batches of work. `Good first issue` labeled. Error message improvements explicitly tracked (#40756) with a pattern PR (#40768) to follow. Mechanical PRs merge quickly.

## Standing

PR #44816 (ElementInternals error messages) merged by jdm on 2026-05-10. Standing earned.

## Issue Scan

### Investigated

| Issue | Title | Labels | Verdict | Notes |
|-------|-------|--------|---------|-------|
| #40756 | Provide actual messages in JS errors | Good first issue | **SELECTED** | Meta-issue tracking error message additions across DOM files. Pattern established by #40768. Picked 3 single-error files: broadcastchannel.rs, blob.rs, domimplementation.rs |
| #44833 | Set introduction type for event handlers | Good first issue, C-assigned | SKIP | Already assigned |
| #42489 | Video controls are not user friendly | Good first issue | SKIP | UI/UX work, not mechanical |
| #42347 | Convert structuredclone::write | Good first issue, C-assigned | SKIP | Already assigned |
| #38901 | Move interfaces into subfolders | Good first issue | DEFER | Large refactor, do after 3+ error message PRs merge |

### Competing PR Density

- High PR volume (~100+ open)
- Many from Igalia team members
- #40756 sub-tasks are file-scoped and don't conflict
- PR #44704 covers cssstylesheet.rs and aes_common.rs
- No competing PRs for broadcastchannel.rs, blob.rs, or domimplementation.rs

## Selected: #40756 (3 small files)

### Hypothesis

**H0:** Multiple DOM files use `Error::**(None)`, providing no descriptive error messages to web developers. The meta-issue #40756 tracks adding messages across the script module, and #40768 established the pattern. Picking the smallest files (1 error each) minimizes scope and review burden.

### Evidence

- Meta-issue #40756 tracks error message improvements across all script/dom files
- PR #40768 established the exact pattern to follow
- broadcastchannel.rs: 1 error (InvalidState on closed channel)
- blob.rs: 1 error (InvalidCharacter in blob parts)
- domimplementation.rs: 1 error (InvalidCharacter on invalid doctype name)

### Fixes

#### broadcastchannel.rs
- Replaced `Error::InvalidState(None)` with message "Cannot post message on a closed BroadcastChannel"
- Branch: `error-messages-broadcastchannel`
- 1 commit (3 insertions, 1 deletion)

#### blob.rs
- Replaced `Error::InvalidCharacter(None)` with message "Invalid character in blob parts"
- Branch: `error-messages-blob`
- 1 commit (5 insertions, 1 deletion)

#### domimplementation.rs
- Replaced `Error::InvalidCharacter(None)` with message including the invalid name
- Branch: `error-messages-domimplementation`
- 1 commit (4 insertions, 1 deletion)

## Next Steps

1. Push all 3 branches via drip queue (org-level pacing with servo/servo)
2. After merge: pick next batch from #40756
3. Options: characterdata.rs (2 errors), abortsignal.rs (3 errors), dissimilaroriginlocation.rs (6 errors)
4. Avoid cookiestore.rs (8 errors) until smaller files prove the pattern
