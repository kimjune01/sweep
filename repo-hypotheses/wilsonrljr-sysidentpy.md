# Triage Graph: wilsonrljr/sysidentpy

**Date:** 2026-05-11  
**Stars:** 499  
**Issues:** 7 open  
**Language:** Python  
**Maintainer:** wilsonrljr (Wilson Rocha Lacerda Junior)

## Repo Context

Python package for System Identification using NARMAX models. Built on NumPy, with neural network support via PyTorch. Active research-oriented project with companion book. Maintainer is solo developer, actively engaged with contributors via Discord.

## Triage Sessions

### Session 1: 2026-05-11 (Initial scan, fix for #193)

**Outcome:** 1 branch created (`add-include-bias-polynomial`)

Fixed issue #193 - smallest and most tractable issue in the backlog. Added `include_bias` parameter to Polynomial basis function to match newer basis functions like Legendre.

## Issue Analysis

### #193: Add `include_bias` option for basis function (FIXED)

**Status:** Fixed in branch `add-include-bias-polynomial`  
**Type:** Enhancement - API consistency improvement  
**Maintainer-filed:** Yes (wilsonrljr)  
**Milestone:** v1.0.0  
**Assignee:** wilsonrljr

**Description:** Currently, some basis functions (like Legendre) have an `include_bias` parameter to optionally add a bias (constant) term, but common basis functions like Polynomial do not. This creates API inconsistency.

**Solution:** Add `include_bias` parameter to Polynomial basis function with:
- Default `include_bias=False` for backward compatibility
- Prepend column of ones when `include_bias=True`
- Handle interaction with `predefined_regressors` correctly
- Support both NumPy and Array API backends

**Files Changed:** 2
- `sysidentpy/basis_function/_polynomial.py`: Implementation
- `sysidentpy/basis_function/tests/test_polynomial.py`: Comprehensive test suite (NEW)

**Test Coverage:**
- Initialization and default values
- Bias inclusion/exclusion
- Shape changes with bias
- Interaction with predefined_regressors
- Backward compatibility with existing behavior

**Review:** Self-reviewed. Implementation follows exact pattern from Legendre basis function. All existing tests pass (backward compatible). New test suite covers edge cases.

**Evidence for H3 (Maintainer-filed issues have clearer acceptance criteria):** SUPPORTED  
Issue description explicitly references Legendre as the pattern to follow and mentions scikit-learn as prior art. Clear API design goal stated.

---

## Full Issue Survey (All 7 Open Issues)

### #229: Expressing Respect and Gratitude (2026-04-10, maintainer responded)
**Type:** Not an issue  
**Body:** Former user expressing gratitude for the project and maintainer's help  
**Maintainer response:** Heartfelt thank you message  
**Verdict:** Skip - human moment, not a code issue

### #193: Add `include_bias` option for basis function (2025-03-27, maintainer-filed) - FIXED
**Type:** Enhancement  
**Verdict:** FIXED in session 1

### #108: Early Stopping for Neural NARX (2023-05-12, "team effort" label, 4 comments)
**Type:** Feature request - complex  
**Body:** Implement early stopping mechanism for neural network training  
**Maintainer:** "Can you send me a message on discord so we can talk to make a plan to work on this?"  
**Contributors engaged:** jamesyan20 (2023), Murad1997 (2024, moved to Discord)  
**Verdict:** Skip for first PR - complex neural network feature, requires Discord coordination for multi-week effort

### #105: Create a base Neural NARX to be imported (2023-05-12, "team effort" label)
**Type:** Refactoring  
**Body:** Extract common neural network functionality into base class  
**Verdict:** Skip - architectural refactoring, requires deep understanding of neural network module

### #100: Create M5 dataset example (2023-05-12, "Documentation" + "team effort" labels, 2 comments)
**Type:** Documentation  
**Contributor:** PedroHPLopes volunteered  
**Maintainer:** Redirected to Discord  
**Verdict:** Skip for first PR - documentation work, unclear if still available after Discord migration

### #99: Add Radial Basis Function (2023-05-12, "team effort" + "Basis Function" labels, 1 comment)
**Type:** Feature - new basis function  
**Contributor:** nataliakeles commented "I really want to work on this issue!"  
**Verdict:** Skip for first PR - uncertain if still available (2023), requires mathematical/numerical knowledge

### #97: SysIdentPy to ONNX (2023-04-28, "needs research" label, 3 comments)
**Type:** Feature request - complex  
**Body:** Export models to ONNX format for deployment  
**Maintainer:** "I don't have any experience with ONNX...we should implement our own converter...If it's something that you could help us with the implementation, I'd be happy to help you along the process."  
**Latest:** Maintainer followed up in 2023-12-21, user hasn't responded  
**Verdict:** Skip - requires ONNX expertise, research-phase feature

---

## Issue Landscape Summary

Out of 7 open issues:
- **1 gratitude message**: #229 (not a code issue)
- **1 enhancement** (API consistency): #193 (FIXED in session 1)
- **3 complex features**: #108 (early stopping), #105 (refactoring), #99 (new basis function)
- **1 documentation**: #100 (example)
- **1 research-phase feature**: #97 (ONNX export)

**Observation:** Issue #193 was the ONLY low-complexity, mechanically implementable issue in the backlog. All others require either:
1. Mathematical/ML expertise (RBF, early stopping)
2. Domain knowledge (ONNX)
3. Coordination via Discord (team effort issues)
4. Architectural understanding (Neural NARX refactoring)

### Code Quality Scan

- **CONTRIBUTING.md present:** Yes - standard fork/PR workflow, testing requirements
- **Test framework:** pytest with coverage
- **No branch policy mentioned** in CONTRIBUTING.md
- **License:** BSD-3-Clause
- **CI:** Appears to use Codacy for code quality and coverage
- **Python versions:** 3.10-3.14

### Maintainer Culture

- **Highly engaged:** Responds to all issues, often redirects complex work to Discord for planning
- **Welcoming tone:** "We welcome new contributors of all experience levels"
- **Team effort label:** Used for issues that need planning/collaboration
- **Milestone tracking:** v1.0.0 milestone exists (issue #193 was assigned to it)

---

## Competing PRs

None found for issue #193 or overlapping scope.

---

## Hypothesis Updates

**H3 (Maintainer-filed issues have clearer acceptance criteria):** STRONGLY SUPPORTED  
Issue #193 had explicit pattern to follow (Legendre), specific parameters to add, and referenced prior art (scikit-learn). Compare to #108 (vague "early stopping" without spec) or #99 (just "Add RBF" with no design).

**H5 (Cold repos need bug fixes first):** PARTIALLY APPLICABLE  
This repo has active contributors (Discord channel, historical PRs) but the issue backlog is small and feature-heavy. Issue #193 was not a bug but an API consistency enhancement - closest thing to "low-hanging fruit" in this repo.

**H6 (Research-oriented repos file issues as planning docs):** SUPPORTED  
Issues #108, #105, #100 have "team effort" label indicating they're not meant for cold contributions. They're planning discussions that may migrate to Discord. Issue #193 stood out as a rare solo-implementable task.

**NEW: H8 (Enhancement issues can serve as standing-builders if mechanically implementable):**  
Not all first PRs need to be bug fixes. API consistency enhancements (like adding missing parameters to match sibling classes) can be low-complexity standing-builders if:
1. Pattern already exists in codebase (copy implementation strategy)
2. Test coverage is straightforward (copy test strategy)
3. No design decisions required (just replication)

---

## Next Steps

**For sysidentpy:** No additional work until:
1. Branch `add-include-bias-polynomial` is dripped and PR'd
2. Monitor for response from maintainer
3. If merged, consider slightly more complex issues (#99 or #100) after earning standing

**For pipeline:** Add enhancement issue detection to /triage:
- Look for issues with "enhancement" label + clear reference implementation
- Rank by:
  1. "Just copy this other class" (like #193)
  2. "Implement this well-defined algorithm" (requires expertise)
  3. "Design and implement" (requires design decisions)
- Prefer (1) for cold repos, (2) after standing earned

---

## Session Notes

- **Devil's advocate check:** Could this break existing code? NO - default `include_bias=False` preserves exact existing behavior
- **TDD applied:** Wrote tests first, verified they'd fail (via manual test harness), then implemented
- **Self-review findings:** None - implementation is straightforward parameter addition following existing Legendre pattern
- **Max 3 rounds:** First round implementation was clean, no iteration needed
