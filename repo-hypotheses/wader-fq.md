# Triage Graph: wader/fq

## Issue #541: Add gentoo install instructions

**Status:** MERGED
**Branch:** add-gentoo-install-docs
**PR:** #1314
**Commit:** d9018fad

### Assessment
- **Type:** Documentation addition
- **Scope:** Minimal - single section in README.md
- **Risk:** Very low - no code changes
- **First contribution:** Yes

### Implementation
Added Gentoo installation instructions to README.md following the same format as other Linux distributions. Placed between Arch Linux and Guix sections to maintain alphabetical ordering.

### Reviews
- **Codex:** Approved - clean implementation following existing patterns
- **Gemini:** Approved - no logic errors, formatting correct, placement appropriate

### Hypothesis mapping
- **H0 (bug fixes merge):** N/A - documentation, not a bug fix
- **H1 (small improvements):** SUPPORTS - documentation improvements are low-friction
- **H2 (standing first):** SUPPORTS - minimal, well-scoped first contribution
- **H3 (features after trust):** N/A - not a feature
- **H4 (maintainer capacity):** SUPPORTS - very low review burden
- **H5 (AI-friendly repos):** UNCERTAIN - repo welcomes contributions but unclear if AI-generated PRs are common
- **H6 (org-level pacing):** N/A - wader is individual maintainer

### Outcome
Merged by wader directly on 2026-05-10.

---

## Issue #452: Apple Binary Property List Enhancement: Timestamps

**Status:** READY
**Branch:** bplist-timestamp-option
**Commit:** 035b6155

### Assessment
- **Type:** Small enhancement with maintainer endorsement
- **Scope:** Decoder option - adds `timestamps` boolean option to bplist format
- **Risk:** Low - optional feature, default behavior unchanged
- **Standing:** Yes - PR #1314 merged

### Implementation
Added `Bplist_In` struct with `timestamps` option to format.go. Modified bplist decoder to convert Cocoa timestamps to Unix timestamps when option is enabled. Conversion adds 978307200 (seconds from Unix epoch 1970-01-01 to Cocoa epoch 2001-01-01).

Default behavior unchanged - dates still shown as Cocoa floats by default. With `timestamps=true`, dates output as Unix timestamps compatible with standard Unix tooling.

### Maintainer guidance
Issue #452 requested this feature. Maintainer @dgmcdona provided explicit guidance in PR #427 comments about how to implement decode options, referencing mp3.go as an example pattern.

### Reviews
- **Pending:** Need codex and Gemini reviews before push

### Hypothesis mapping
- **H0 (bug fixes merge):** N/A - enhancement, not bug fix
- **H1 (small improvements):** SUPPORTS - small, well-scoped improvement with maintainer endorsement
- **H2 (standing first):** SUPPORTS - leveraging merged PR #1314 standing
- **H3 (features after trust):** SUPPORTS - feature addition after successful contribution
- **H4 (maintainer capacity):** SUPPORTS - solo maintainer explicitly requested this
- **H5 (AI-friendly repos):** UNCERTAIN
- **H6 (org-level pacing):** N/A - individual maintainer

### Next steps
1. Run codex review on implementation
2. Run Gemini review on implementation
3. If both pass, add to drip queue
