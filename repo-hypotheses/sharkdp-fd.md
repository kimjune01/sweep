# sharkdp/fd Triage Graph

## Repo Profile
- **Stars:** 42K | **Language:** Rust | **License:** MIT/Apache-2.0
- **Key maintainers:** sharkdp (owner, less active), tmccombs (collaborator, primary reviewer), tavianator (collaborator)
- **Warm lead:** bat #3734 merged by keith-hall in 12min, same collaborator network
- **Review culture:** Small PRs preferred (sharkdp: "PLEASE submit small PRs"). Bug fixes merge. Features need strong justification.

## Issue Landscape (2026-05-10)

### Implemented: #1686 - clarify --full-path help text
- **Type:** documentation bug
- **Labels:** bug
- **Collaborator engagement:** tmccombs asked for suggestions, issue author provided specific text
- **Competing PRs:** None
- **Fix:** Changed help text from "Search full abs. path (default: filename only)" to "Search full path (default: the last element of the path)"
- **Status:** Implemented, tested (105/105 pass), committed to `fix/full-path-help-1686`
- **Risk:** Minimal. 1 line changed, docs-only, requested by tmccombs

### In flight: #1944 - shell builtin hint in command-not-found error
- **Type:** documentation/UX bug
- **Labels:** documentation
- **Collaborator engagement:** tmccombs responded 3x, phuclv90 suggested concrete fix
- **Competing PRs:** None
- **Fix:** When `fd -x` gets NotFound for a known shell builtin, add hint to error message
- **Status:** PR #1994 open since 2026-05-09, awaiting review
- **Risk:** Low. 1 file changed, pure error-path logic, no behavior change for valid commands

### Rejected candidates

| Issue | Reason |
|-------|--------|
| #1932 grammar fix | Already fixed by PR #1934 (commit f8baea8), issue stale |
| #1017 --min-depth broken symlinks | Competing PR #1990 already open (mitre88), changes requested by tavianator |
| #839 --full-path rel-path matching | Feature request, sharkdp rejected twice, reopened but no clear design consensus |
| #1985 deep directories | Labeled upstream-error (walkdir limitation), tmccombs says "quite difficult" |
| #1965 light/dark themes | Depends on LS_COLORS, unclear acceptance criteria |
| #1693 -e matches directories | Collaborator says "can't change behavior", documentation-only fix at most |
| #1650 glob ** not working | Requires complex validation logic, tavianator suggested warning but implementation scope unclear |
| #1775 --list-details error | Reporter says "no longer appears with latest (10.3.0)" - already fixed |

### Open PRs competing density
- 30 open PRs total, 3-4 from mitre88 (prolific contributor)
- tmccombs active as both contributor and reviewer
- Feature PRs (#1866 --json, #1856 --type leaf, #1847 detailed listing) stalling without review
- Docs PRs merge faster than feature PRs

### Pipeline notes
- Bug fixes merge at this repo. Features don't unless sharkdp personally approves.
- tmccombs is the gateway reviewer. His LGTM is necessary and often sufficient.
- Small, well-tested PRs with clear issue linkage get fastest review.
- Docs improvements have clear acceptance path (#1979 PowerShell docs, #1953 macOS spelling both merged)

## Session summary (2026-05-10)
- Completed 2 issues out of requested 5
- #1944 already in PR review (opened 2026-05-09)
- #1686 newly implemented, ready to push
- Most other "easy" issues are either:
  - Already fixed (closed PRs but issue still open)
  - Have competing PRs
  - Require feature-level design decisions
  - Need complex implementation (glob validation, upstream library changes)
- Repo has high bar for new features, lower bar for docs/error message improvements
- Standing from bat #3734 provides warm introduction

## Hypothesis coverage
- **H0 (cold start):** Warm lead via bat network. First PR (#1994) is a low-risk bug fix, second (#1686) is docs improvement.
- **H1 (review latency):** tmccombs typically responds 1-2 days for bug/docs PRs. #1994 opened 2026-05-09, still within expected window.
- **H2 (competing PRs):** Checked -- no competition for #1944 or #1686. Avoided #1017, #1650, #1932 due to existing PRs or fixes.
- **H3 (scope creep):** Both PRs tightly scoped: #1944 error message formatting, #1686 single help string.
- **H4 (test coverage):** All tests passing (248/248 for #1944, 105/105 for #1686). Built successfully.
- **H5 (maintainer taste):** Both align with merged PRs: #1979 (docs), #1953 (spelling), #1975 (error messages).
