# pytorch/pytorch Triage Graph

Generated: 2026-05-09

## Repository Profile

- **Stars:** 100K+
- **Primary language:** Python, C++
- **Active programs:** Docathon 2026 (May 5-17), PT2-Bug-Bash
- **Merge pattern:** Bug fixes merge readily; features require internal champion

## Scanned Issue Classes

### 1. Docathon RST-to-MyST Conversions (docathon-2026 label)

- 30+ RST files remaining in `docs/source/`
- All filed issues are self-assignable via `/assigntome`
- **Status: ALL ASSIGNED** as of 2026-05-09
- Difficulty: easy (RST conversions), medium (document undocumented functions)
- Window closes May 17

### 2. Good First Issue Bugs (good first issue label)

- 30 open, 21 unassigned
- Most are PT2/dynamo/inductor related (high complexity despite label)
- Many have stale competing PRs that were never merged

### 3. Triaged + Actionable Bugs

- Rich pipeline of unassigned, triaged, actionable issues
- Best candidates for first contribution: error checking / silent bug fixes

## Issue Evaluation

### Selected: #173049 - OOM error suggests expandable_segments even when enabled

- **Type:** Bug fix (error checking, UX)
- **Labels:** triaged, actionable, module: cuda, module: CUDACachingAllocator
- **Assignees:** None
- **Competing PRs:** #173051 (closed by stalebot, never reviewed)
- **Complexity:** Low - single file, 12 insertions / 4 deletions
- **Acceptance criteria:** Clear - suppress suggestion when config is already set
- **Review gates:** codex approved, gemini approved
- **Branch:** `fix/oom-expandable-segments-suggestion`
- **Commit:** `91e8eb0`

### Rejected Candidates

| Issue | Reason |
|-------|--------|
| #182058+ (docathon RST) | All assigned |
| #171905 (TypeAliasType) | 5+ competing open PRs |
| #137285 (torch logs docs) | Actually tutorials repo, PRs exist |
| #163759 (torch.combinations) | 2 competing open PRs |
| #110950 (ruff checks) | 2 competing open PRs |
| #117351 (fx.Interpreter) | Already implemented in codebase |
| #129020 (tags: views/reductions) | Complex, requires native_functions.yaml changes |
| #180377 (linalg.qr overlap) | Open competing PR #180420 |
| #175994 (CentOS docker) | Open competing PR #176071 |

## Fix Details

**File:** `c10/cuda/CUDACachingAllocator.cpp`

**Change:** Conditionally build the expandable_segments suggestion string in the CUDA OOM error message. Uses `AcceleratorAllocatorConfig::use_expandable_segments()` (raw atomic config) rather than `CUDAAllocatorConfig::expandable_segments()` (platform-gated) so the suggestion is suppressed even when the user set the flag on an unsupported platform.

**Placement:** After `lock.unlock()` since the config read is an atomic bool and does not need allocator state. This keeps the lock scope tighter.

**Codex notes:** Approved. Flagged the use_expandable_segments vs expandable_segments distinction (addressed). Suggested moving after lock.unlock (addressed).

**Gemini notes:** Approved. Confirmed thread-safety of atomic read after unlock. Flagged minor UX gap on unsupported platforms (out of scope for this PR, pre-existing behavior).
