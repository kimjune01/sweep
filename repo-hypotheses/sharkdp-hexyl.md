# sharkdp/hexyl Triage Graph

## Repository Context

- **Owner**: sharkdp (David Peter)
- **Repo**: hexyl (hex viewer)
- **Stars**: ~10K
- **Language**: Rust
- **Org context**: Warm - sharkdp/bat#3734 MERGED (2024)
- **Maintainer style**: Clear API design, prefers explicit options, values clean PRs

## Issue Scoring

### #227 - Bold output similar to xxd (IMPLEMENTED)
- **Score**: 9/10
- **Maintainer signal**: Explicit approval with API design specified
- **Acceptance criteria**: `--emphasize=nothing` (default), `--emphasize=non-zero`
- **Competing PRs**: None
- **Status**: IMPLEMENTED on branch master (commit 2e2b0f8)
- **Implementation notes**:
  - Codex provided initial implementation
  - Gemini caught bug: byte_hex_panel_g (gradient scheme) not emphasized
  - Fixed and verified with both Default and Gradient color schemes
  - All 41 tests pass

### #155 - Shell completions
- **Score**: 8/10
- **Maintainer signal**: Approved, suggested clap_complete
- **Acceptance criteria**: Auto-generated completions using clap_complete
- **Competing PRs**: None active
- **Notes**: Clean implementation path, low risk

### #236 - NULL byte color/glyph
- **Score**: 6/10
- **Maintainer signal**: Engaged but undecided on approach
- **Acceptance criteria**: Unclear - maintainer wants themes or per-color control
- **Competing PRs**: None
- **Notes**: Requires design discussion before implementation

### #228 - Large file position alignment
- **Score**: 7/10
- **Maintainer signal**: Acknowledged
- **Acceptance criteria**: Fix alignment for positions >2^32
- **Competing PRs**: #255 (open PR addressing this)
- **Notes**: Skip - competing PR exists

### #231 - Config file
- **Score**: 6/10
- **Maintainer signal**: Approved for env vars, asked which settings
- **Acceptance criteria**: Environment variable support for common settings
- **Competing PRs**: None
- **Notes**: Requires scoping which settings to support

## Denied Issues

None yet.

## Pipeline Evidence

- **H0 (actionable signal)**: #227 confirmed - maintainer provided explicit API design
- **H1 (mechanical criteria)**: #227 confirmed - tests pass, both color schemes work
- **H2 (competing work)**: #228 has competing PR #255 - skip per memory
- **H5 (org-level pacing)**: sharkdp org warm (bat#3734 merged), drip gate ready

## Next Steps

1. Push #227 to remote when drip queue allows
2. Consider #155 (shell completions) as next target - clear path, maintainer approved
3. Monitor #228/#255 - if #255 stalls, could be opportunity
