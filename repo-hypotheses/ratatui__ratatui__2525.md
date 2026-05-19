# ratatui/ratatui#2525 — reinvestigate (CI red)

PR: fix(layout): account for overlap in Ratio and Percentage constraints
Head: `fix/ratio-overlap-spacing` @ `e018f1c9` (pre-fix), `96f2a1d` (post-fix)

## H₀ — Clippy red on stable + beta; doc_markdown rejects identifiers

- **Source.** Job 75170878202 log tail: 5 × `clippy::doc_markdown` errors at `ratatui-core/src/layout/layout.rs:2951` and `:2986`. Compile fails with `-D warnings`.
- **Identifiers flagged.** `Spacing::Overlap`, `Constraint::Ratio` (L2951); `SpaceBetween`, `SpaceEvenly`, `SpaceAround` (L2986). All inside `///` doc comments on the new `#[rstest]` test and the `distributed_flex_overlap_uses_physical_area` test.
- **Reasoning mode.** Deduction (compiler/lints are 100% precise). Confidence 99%.
- **Trajectory shape.** Divergent — single root cause, mechanical fix.
- **Edge.** Wrap each identifier in backticks. No code-path change, test-only doc.

## Fix

Two one-line edits in `ratatui-core/src/layout/layout.rs`:
- L2951: `Spacing::Overlap and Constraint::Ratio` → `` `Spacing::Overlap` and `Constraint::Ratio` ``
- L2986: `(SpaceBetween, SpaceEvenly, SpaceAround)` → `` (`SpaceBetween`, `SpaceEvenly`, `SpaceAround`) ``

## Verification

`docker run sweep-tester:latest cargo clippy -p ratatui-core --tests --all-features -- -D warnings` → `Finished` with no errors (vs. 5 errors pre-fix).

Commit `96f2a1d` pushed to `kimjune01/ratatui:fix/ratio-overlap-spacing`. CI will re-run on push.

## Frontier

None — clippy was the only red gate, mergeable=MERGEABLE, review_decision=REVIEW_REQUIRED is reviewer time, not a code issue.

## Reinvestigate revisit 2026-05-18

Context pack was stale (referenced pre-fix SHA `e018f1c`). Live PR state at head `96f2a1d`: 33 SUCCESS, 2 still running, 0 FAILURE; mergeable=MERGEABLE. Clippy fix from prior cycle already shipped and green. No-op — close cycle.
