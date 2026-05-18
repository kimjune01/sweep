# tuono-labs/tuono#839 — Hypothesis Graph

**PR:** https://github.com/tuono-labs/tuono/pull/839
**Issue:** #580 (jacobhq, 2024)
**Author:** kimjune01
**State (2026-05-17):** OPEN, MERGEABLE, no reviews, CI = `action_required` (6 workflows)
**Diff size:** +1 line

## Summary

PR adds `#[cfg(not(target_os = "windows"))]` above a `Command::new("chmod")` call in `crates/tuono/tests/cli_build.rs::it_fails_without_installed_build_script`. Issue #580 reports the test panics on Windows because `chmod` doesn't exist there.

## H₀ — The fix is structurally sound

- **Hypothesis.** Guarding the chmod with `cfg(not(windows))` is the minimal correct change.
- **Null.** Either it under-fixes (test still fails on Windows for a different reason) or over-fixes (skips logic that mattered on Windows).
- **Perturbation.** Read the diff + the surrounding test + the original Windows panic backtrace.
- **Evidence.** The Windows panic from #580 is exactly `Failed to spawn Command { cmd: "chmod" ... }: program not found` from `assert_cmd`. The guard prevents the spawn. The remaining assertions (`cargo_bin("tuono") ... build ... failure ... stderr("Failed to read config...")`) are platform-agnostic.
- **Trajectory.** Divergent for. Confirmed by code reading.
- **Edge.** None — the structural change is minimal and matches the surrounding code (no prior `cfg` gates in this file, so the standard Rust idiom is the right pick).
- **Mode.** Deduction. Confidence 95%.

## H₁ — The Windows test path still produces the asserted failure mode

- **Hypothesis.** On Windows, with `tuono-build-config.cmd` containing `#!/bin/bash` and no chmod, `tuono build` still fails with `"Failed to read config. Please run `npm install` to generate automatically.\n"` to stderr.
- **Null.** Windows produces a different failure (e.g. cmd interpreter runs the `#!/bin/bash` line as a malformed batch command, or succeeds silently and tuono produces a different error).
- **Perturbation.** CI on `windows-latest` (already in the Rust CI matrix at `rust-ci.yml`).
- **Evidence.** Not yet collected — CI is `action_required`, never executed.
- **Trajectory.** Pending.
- **Mode.** Abduction. Confidence 70% — the config-read failure happens *before* tuono attempts to execute the config script, so the chmod state shouldn't matter, but we have no measurement.
- **Edge.** Wait for maintainer to approve CI run.

## H₂ — CI approval is the only ship blocker

- **Hypothesis.** Bottleneck is procedural, not technical: first-time contributor PRs in this repo require maintainer click-through before any workflow runs.
- **Null.** Some workflow is silently failing or a required check is misconfigured.
- **Perturbation.** `gh api .../actions/runs?head_sha=<sha>` — list workflow runs at the PR HEAD.
- **Evidence.** All 6 workflows (`Rust CI`, `Repo root CI`, `E2E CI`, `Examples CI`, `PR Title Checker`, `Typescript CI`) show `conclusion: action_required, event: pull_request`. Only `PR Labeler` (pull_request_target) ran. This is GitHub's standard first-time-contributor gate.
- **Trajectory.** Divergent for.
- **Mode.** Induction (measured the workflow run states). Confidence 95%.
- **Edge.** No engineering work can de-risk further until CI runs.

## Graph state

| Node | Status | Shape | Mode | Confidence |
|------|--------|-------|------|------------|
| H₀ minimal correct change | Confirmed | Divergent for | Deduction | 95% |
| H₁ Windows still asserts target stderr | Pending | — | Abduction | 70% |
| H₂ CI approval is the blocker | Confirmed | Divergent for | Induction | 95% |

## Provenance

- **Origin of code under change.** `crates/tuono/tests/cli_build.rs` test `it_fails_without_installed_build_script` — chmod-only path, no platform gating in the file.
- **Upstream search.** No competing PRs for #580 (`gh pr list --search "windows chmod" --state all` returns only #839).
- **Author of issue ≠ author of PR.** No self-PR halt.

## Reframe (Phase 4.5)

This is not an engineering investigation — the fix is one line, structurally sound, and the remaining frontier (H₁) can only be classified by CI hardware we don't own. The diagnosis is procedural: the PR is parked behind GitHub's first-time-contributor CI approval gate.

**No prework, no benchmark, no bug hunt.** None of these change the answer. The action is to wait for maintainer approval; if it stalls, a polite ping is the only available perturbation.

## Frontier

- **H₁** — pending CI. When the maintainer approves the workflow run, classify the Rust CI trajectory on `windows-latest`. Divergent for → ship. Anything else → re-enter the graph with the failure mode as a new H₀.

## Halt

Frontier holds open on H₁ but requires an external action (maintainer CI approval). No further local perturbation is informative. Re-enter when CI status changes.
