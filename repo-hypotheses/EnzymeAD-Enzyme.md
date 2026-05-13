# EnzymeAD/Enzyme Triage Graph

Repo: https://github.com/EnzymeAD/Enzyme
Hypothesis coverage: H0 (LLVM/MLIR autodiff), H6 (academic maintainer responsiveness)
Maintainer: @wsmoses (William Moses, MIT)
Fork: https://github.com/kimjune01/Enzyme

## Maintainer Preferences (learned from PR #2816 review by wsmoses)

- MLIR tests: use post-transform IR (after --outline-enzyme-regions), not pre-transform
- Test CHECK lines: full CHECK-NEXT sequences, not partial CHECK-DAG
- Error handling: return failure explicitly, never silent fallthrough
- Diffe zeroing: mandatory even when container is constant ("required even if the container is constant")
- Review style: approves conditionally with inline comments, expects follow-up commit addressing all points
- Standing: first PR, wsmoses engaged with 6 inline comments — active reviewer, not batch processor

## Repo Profile

- LLVM/MLIR automatic differentiation framework
- 5 good-first-issues, academic project with weekly meetings
- Active collaborators: @tgymnich, @minansys, @vimarsh6739
- CI: clang-format-16 (LLVM style), lit tests via `%eopt`
- Bot PR density: moderate (copilot-swe-agent has 3 open PRs)

## Issue Scan (2026-05-09)

### Selected: #2811 + #2812 (PAIRED)
- **Title**: No ReverseAutoDiffOpInterface registration for llvm.extractvalue / llvm.insertvalue
- **Author**: @xys-syx (2 days old)
- **Labels**: none (unlabeled bugs)
- **Competing PRs**: NONE
- **Type**: Bug fix -- missing interface registration causes crash
- **MRE**: Both issues include minimal reproducing MLIR code
- **Fix**: Register ReverseAutoDiffOpInterface for ExtractValueOp and InsertValueOp
- **Status**: COMMITTED on branch `fix/llvm-insertvalue-extractvalue-reverse-ad`
- **Reviews**: codex PASS (with type guard improvement applied), gemini PASS (hard gate cleared)

### Rejected candidates

| Issue | Title | Reason |
|-------|-------|--------|
| #2784 | NVVM barrier args wrong | Competing PR #2785 (copilot-swe-agent), already approved by @minansys |
| #2700 | eraseFictiousPHIs crash | Competing PRs #2699 and #2793 by @minansys |
| #2794 | invertPointerM crash | Author (@minansys) is a collaborator who self-fixes; tinyurl body |
| #2789 | Heap corruption std::vector | No MRE, unclear reproduction |
| #2796 | AtomicLoadFAdd clang19+ | CUDA-specific, no MRE, hardware dependent |
| #962  | Track cached/recomputed values | good-first-issue but feature, not bug fix |
| #839  | Collect string constants into enums | Feature, stale (2022) |

## Hypothesis Notes

- **H0 (LLVM/MLIR autodiff)**: Enzyme is the canonical test case. MLIR dialect AD is actively developed. Missing interface registrations are genuine bugs with mechanical fixes.
- **H6 (academic responsiveness)**: @wsmoses reviews actively but selectively. Bot PRs get reviewed but often require multiple rounds. Human PRs from collaborators merge faster. First-time contributors should target clear bugs with MREs.
