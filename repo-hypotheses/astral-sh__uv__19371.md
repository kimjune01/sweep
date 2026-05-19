# Hypothesis Graph: astral-sh/uv#19371

**Status:** HALT — design-consensus block, not a code problem.
**Mode:** reframe at Phase 1.

## H₀ — "Our PR needs technical iteration to merge"

- **Perturbation:** read the PR thread and referenced PRs.
- **Observation:**
  - Our PR #19371 (open, kimjune01): switches `LockMismatch` print sites to `stderr_important()`.
  - PR #19337 (closed): same fix shape, same files, same rationale.
  - PR #19333 (open, CHANGES_REQUESTED): same fix shape, same rationale, blocked by maintainer review.
  - woodruffw on #19371: "almost certainly the same as #19337, i.e. a duplicate of #19333 that we don't have a design consensus for."
  - woodruffw on #19333 (the original): *"I'm not sure if we want to do this — per other conversations, we don't really have a plan around consistently using important-or-not at the moment. We probably need to make a decision about that before accepting this kind of change."*
- **Trajectory:** divergent against H₀. The block is **design policy** on `stderr_important()` usage, not a defect in any single PR's code.
- **Killed by:** explicit maintainer statement on the predecessor PR.

## Reframe

The original framing ("fix the silent error under `--quiet`") is correct as a bug report but wrong as a code-investigation target. The bug is real (#19326 is open and the symptom reproduces), but the maintainers have an outstanding **policy question**: when is `stderr_important()` the right writer? Until that's resolved upstream, *any* PR switching call sites to `stderr_important()` gets the same CHANGES_REQUESTED, regardless of code quality, tests, or scope.

Our PR is the third instance of that pattern. Pushing a fourth iteration — better tests, smaller diff, different call-site selection — does not move the maintainer's blocker. The blocker is upstream of the code.

## Frontier

- **Edge (open, human-gated):** does the operator want to leave #19371 open as a vote/example for the policy discussion, close it deferring to #19333, or post a comment offering to help draft the `stderr_important()` policy if the maintainers describe their criteria?
- All three options are social moves, not code moves. The investigate skill cannot pick among them — it requires operator judgment about how to engage with this maintainer.

## Provenance

- **Reasoning mode:** deduction (read maintainer's own words on a sibling PR).
- **Confidence:** ~98% that any code-shaped iteration on #19371 is wasted until the upstream policy resolves.
- **Source:** `gh api repos/astral-sh/uv/pulls/19333/reviews` and the context pack comment on #19371.

## Pruning log

- Skipped Phase 2 fan-out: no point generating competing code hypotheses when the kill condition is "no code change in this shape will land."
- Skipped Phase 5/6/7: prework, benchmark, bug-hunt all operate on a fix; the fix is fine, the policy isn't.
