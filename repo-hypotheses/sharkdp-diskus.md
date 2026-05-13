# sharkdp/diskus Triage Graph

## Metadata
- Repo: sharkdp/diskus
- Org: sharkdp (warm - bat MERGED)
- Language: Rust
- Domain: CLI disk usage tool
- First contribution: yes
- Triaged: 2026-05-10

## Issues Processed

### #41: Provide path in output ✅ IMPLEMENTED
- **Status**: good first issue, maintainer-acknowledged ("Sounds great!")
- **Request**: Add flag to print path alongside size
- **Branch**: add-print-path-flag
- **Complexity**: Low - CLI flag + output formatting
- **Decision**: Implemented with `--print-path` flag
- **Implementation notes**:
  - Tab-separated output for machine parseability
  - Rejects multiple paths to avoid ambiguity
  - Codex review addressed: removed library API changes, used tab separator
- **Queue entry**: sharkdp-diskus.jsonl

### #42: Handling junctions in Windows
- **Status**: Windows-specific, maintainer not working on it
- **Decision**: SKIP - maintainer stated "not a Windows user", low merge probability

### #43: Undocumented stdout behaviour
- **Status**: Documentation + feature request
- **Complexity**: Medium - needs both docs and possibly CLI flag
- **Decision**: SKIP - documentation updates require understanding all edge cases

### #44: Add an option to follow symlinks
- **Status**: enhancement, maintainer-acknowledged
- **Complexity**: Medium - symlink handling logic
- **Decision**: SKIP for first PR - save for after #41 merges

### #53: Usage with xargs
- **Status**: user error, maintainer pointed out command issue
- **Decision**: SKIP - not a code issue

## Hypothesis Evidence

- **H1 (good-first-issue works)**: #41 labeled, maintainer-acknowledged, straightforward impl → SUPPORTS
- **H2 (warm org helps)**: sharkdp/bat MERGED, same maintainer → TBD (waiting for PR review)
- **H4 (small scope merges)**: #41 is minimal CLI addition → SUPPORTS

## Next Steps

1. Wait for drip to push PR for #41
2. If #41 merges, consider #44 (symlinks) for second PR
3. Monitor for new good-first-issue labels
