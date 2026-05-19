# Hypothesis Graph: sharkdp/fd#1994 (reinvestigate)

## Context
- PR: fix: hint shell builtins in command-not-found error (#1944)
- Failing check: `Ensure 'cargo clippy' has no warnings` (clippy::manual-contains)
- Maintainer-adjacent contributor (leno23) left explicit one-line fix in 5 comments.

## H₀ — CI fail is `clippy::manual-contains`
- Observation: `SHELL_BUILTINS.iter().any(|&b| b == program)` in `src/exec/command.rs:112` triggers `clippy::manual-contains` (lint stabilized in recent stable, this PR was authored before that).
- Perturbation: replace with `SHELL_BUILTINS.contains(&program)`.
- Trajectory: divergent confirm — clippy passes locally on sweep-tester:latest after edit.
- Mode: deduction. Confidence 99%.
- Status: **confirmed / shipped**. Commit `28f15a9` already on remote branch from a prior cycle; context pack was stale.

## H₁ — Mergeable=CONFLICTING (separate failure mode surfaced)
- Observation: `gh pr view` shows mergeable=CONFLICTING despite CI fix being pushed.
- Perturbation: `git merge origin/master` → CHANGELOG.md conflict at the bugfix list (purely additive — #849 entry landed on master while the #1944 entry sat in this PR).
- Trajectory: divergent confirm.
- Resolution: keep both entries; #849 first (it landed first on master), #1944 second.
- Pushed merge commit `10f0c97`.
- Mode: deduction. Confidence 99%.
- Status: **confirmed / shipped**.

## Frontier
- CI on `10f0c97` not yet enqueued at investigate time. Expected: green (clippy fixed, merge resolved, no functional changes).
- If CI red on a different check, re-enter as new H₀.

## Cycle 2026-05-18 (no-op reinvestigate)
- Context pack still cached the old failing run on 1fd9e70 (`reinv-ctx-prstate` headers stale).
- Live state: `gh pr view 1994` → `mergeable=MERGEABLE`, head=`10f0c97`, fresh CICD run 26056160415 in_progress; clippy + fmt checks already green; remaining matrix builds queued/running. Matches H₁ prediction.
- No perturbation needed. Halt — pipeline is just waiting for CI to drain. Substrate should suppress reinvestigate fires on this PR until either a real check flips red on `10f0c97` or a new commit lands.

## Pruning log
- None — both hypotheses survived. No dead ends this cycle.

## Notes
- Context pack head SHA (1fd9e70) was stale; actual remote head was 28f15a9 with clippy already addressed. Sweep substrate caches issue/PR state; a prior cycle pushed the fix without updating the cached SHA.
- leno23 offered to close PR #1998 if this PR lands first. After merge, recommend a brief thank-you comment.
