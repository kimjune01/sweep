# FolkComputer/folk Triage Graph

**Repo**: FolkComputer/folk (227 stars, C/Tcl)  
**Description**: Physical computing system  
**Issues**: 24 open  
**Triage Date**: 2026-05-11  
**Outcome**: NO ACTION - Unsuitable for cold contribution

## Analysis

### Repo Characteristics
- **Pre-alpha state**: README explicitly warns "isn't yet well-documented or well-exampled", "Try at your own risk"
- **Active refactoring**: PR #261 (+1712/-611, 25 files) shows major architectural changes in progress
- **Domain complexity**: Physical computing system with projector/camera calibration, AprilTag detection, Tcl-based reactive language
- **Specialized hardware**: Requires dedicated PC, webcam, projector, printer setup

### Issues Reviewed

#### #218: "Wish $this draws a rectangle" persists after program reset
- **Symptom**: Ctrl+R reset clears editor code but leaves visual wishes active
- **Root cause**: Reactive statement lifecycle - reset clears edited code buffer but doesn't retract active wishes
- **Complexity**: Requires understanding Folk's When/Wish/Claim reactive evaluator, statement matching, and lifecycle management
- **Verdict**: Core architecture issue, high risk

#### #168: live-build fix keyboard?
- **Content**: "add user to tty group?"
- **Complexity**: System installer/deployment issue, not a code bug
- **Verdict**: Infrastructure work, unclear requirements

#### #167: Make live-build installer work
- **Content**: Empty body
- **Complexity**: Installer infrastructure
- **Verdict**: No specification

#### #102: Folk journal fills disk if there's some per-frame error
- **Content**: "/var/log/syslog can become 50GB, 100GB, 200GB"
- **Complexity**: System logging configuration, not application code
- **Verdict**: Operations/deployment issue

#### #70: No way to specify text colors, sizes, etc.
- **Content**: Feature request for inline DSL `[bg red] red text`
- **Complexity**: Language design decision + GPU rendering pipeline changes
- **Verdict**: Feature request, not a bug

#### #135: Add spaces to color parsing
- **Content**: Support `rgb(1, 2, 3)` instead of `rgb(1,2,3)`
- **Complexity**: Requires understanding statement parsing and "custom readers" architecture
- **Verdict**: Parser enhancement, moderate complexity but unclear acceptance criteria

#### #170: Properly fix the assignment of Control characters in keymap.tcl
- **Content**: "feels like a hack... proper fix is to avoid adding Control_* to chars"
- **Complexity**: Code quality issue in keyboard input handling
- **Verdict**: Refactoring request, requires domain expertise

#### #55: Better statements web page (GOOD FIRST ISSUE)
- **Content**: Add fuzzy search, filtering, ancestor/descendant links
- **Complexity**: Web UI + understanding statement database structure
- **Verdict**: Most accessible issue, but still requires Folk internals knowledge

### Competing Work
- PR #261: Major drawing system refactor (May 7, 2026) - likely conflicts with any shape/display work
- 6 open PRs total, including WebRTC (2024), program ID changes (2024)

### Hypotheses

#### H0: AI-friendly policies increase supply
- **Evidence**: ❓ No CONTRIBUTING.md, no explicit contribution policy
- **Interpretation**: No signal either way

#### H1: Maintainer responsiveness → merge rate
- **Evidence**: ❌ Issue #170 (Aug 2024) has maintainer self-review but no resolution. Issue #168 (Aug 2024) has no comments.
- **Interpretation**: Low issue activity suggests limited maintainer bandwidth

#### H2: Test-first contributions earn trust
- **Evidence**: ✅ Has test/ directory with .folk test files
- **Interpretation**: Testing infrastructure exists but unclear how to write tests for issues (no test framework docs)

#### H3: Bug fixes merge, features don't
- **Evidence**: ⚠️ Most open issues are feature requests or architecture discussions, not clear bugs
- **Interpretation**: Bug surface is unclear in pre-alpha state

#### H4: Documentation contributions always welcome
- **Evidence**: ❌ Issue #55 (Jul 2023, "good first issue") has 2 comments but no PR
- **Interpretation**: Even "good first issue" lacks traction

#### H5: Specification precision → acceptance
- **Evidence**: ❌ Multiple issues have vague specs: #167 (empty), #168 (one-liner), #170 ("feels like a hack")
- **Interpretation**: Issues are notes-to-self, not external contribution specs

#### H6: Cold contributors vs. sustained engagement
- **Evidence**: ✅ Recent PR #261 is from @andrescuervo (maintainer per README)
- **Interpretation**: Active development is maintainer-driven

### Recommendation

**DO NOT PURSUE**. This repo fails basic actionability criteria:

1. **No clear bugs**: Issues are feature requests, architecture questions, or infrastructure work
2. **Pre-alpha flux**: Active refactoring makes contribution targets unstable
3. **Domain barrier**: Requires physical hardware setup + deep Folk language knowledge
4. **Low external contribution**: "Good first issue" #55 is 2 years old with no PR

#### Risk Factors
- No test-first entry point (unclear how to write tests)
- README warns of "no guarantee of support, usability, or backward compatibility"
- Recent large PR suggests codebase in motion
- Issues are maintainer working notes, not external contribution specs

#### Alternative Strategy
If pursuing Folk were strategic (e.g., research interest in physical computing), better approach:
1. Build physical setup (hardware investment required)
2. Use the system extensively to understand Folk language
3. Engage on Discord (mentioned in #70) to understand maintainer priorities
4. Wait for post-alpha announcement when contribution model stabilizes

For the triage pipeline's objective (earn trust → open issues → become maintainer), Folk is unsuitable at this stage.
