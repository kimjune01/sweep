# pvolok/mprocs#211 Hypothesis Graph

Issue: configurable logging option for main process
Date: 2026-05-18
State: partial, blocked before executable perturbation

## Routing

- `sweep project-info pvolok/mprocs` returned canonical worktree `/Users/junekim/.sweep/worktrees/pvolok__mprocs`, `worktree_exists: false`, `test_env: docker:sweep-tester:latest`, no canonical test command.
- Creating `/Users/junekim/.sweep/worktrees/pvolok__mprocs` was denied by filesystem permissions.
- Cloning to `/Users/junekim/Documents/sweep/worktrees/pvolok__mprocs` failed because local network/DNS access to GitHub is unavailable.
- Perturbation access to the actual codebase is therefore unavailable in this run. Per rule, no PR-ready fix can be produced from this environment.

## Evidence Pack

- Issue body: every quit on mprocs v0.8.3 on NixOS creates `mprocs.log` containing `ERROR [lib::error] Error: channel closed`; user says behavior otherwise works and asks either to fix the error or make logging optional/configurable.
- Current public source excerpts from GitHub/docs.rs show `src/mprocs.rs::setup_logger()` builds a `flexi_logger` file logger with release level `warn`, `FileSpec::default().suppress_timestamp()`, and `.append()`.
- `run_app()` unconditionally calls `let logger = setup_logger();` immediately before spawning kernel/client work and drops the logger after `client_main(...)` returns.
- Existing documented CLI/config knobs `--log-dir`, `--log-file`, `--log-mode`, and `proc_log` configure process logs, not this main-process logger.
- Shutdown-adjacent code includes `.log_ignore()` calls and `UnixProcessesWaiter::uninit().log_ignore()`, but the exact emitter of `Error: channel closed` has not been proven.

## Blind Pushout Merge

### Where A and B diverge

- A names the panic hook as a possible contributor; B treats the panic hook as background risk and focuses on shutdown result logging. Neither has evidence of panic on normal quit.
- A proposes explicit main-log configurability as a secondary feature; B prefers suppressing/downgrading the specific benign shutdown result first. Both agree configurability is separate from the root error.
- A's decisive perturbation is to skip `setup_logger()` or redirect it; B's is to set release logging to off/no-op. These are equivalent for file-creation classification, but neither identifies the exact channel-close source.

### Agreement

Both independently converge on the same high-level mechanism: unconditional main-process file logging makes any shutdown `ERROR` record create or append `mprocs.log`; the exact `channel closed` producer remains unproven.

## Graph State

| Node | Status | Trajectory | Confidence | Summary |
|---|---|---|---:|---|
| H0 | killed | divergent | 90% | Null "normal quit should not create a main log file with an error" is contradicted by issue observation. |
| H1 | partial | convergent | 78% | Unconditional main logger explains why `mprocs.log` is created and why process-log config does not help. |
| H2 | open | pending | 55% | A benign shutdown channel close is logged as `ERROR` during normal quit. Exact source unknown. |
| H3 | open | pending | 50% | The requested fix should be a logging configurability flag for main-process logging rather than source-level shutdown suppression. |
| H4 | blocked | chaotic | 35% | The bug may already be fixed or changed after v0.8.3/master excerpts; local source and full history are unavailable. |

## Nodes

### H0: Baseline Observation

- Hypothesis: mprocs exits cleanly without creating a main-process error log on normal quit.
- Null: normal quit produces no `mprocs.log` with an error.
- Perturbation: user ran mprocs v0.8.3 on NixOS and quit normally.
- Observation: `mprocs.log` is created every quit with `ERROR [lib::error] Error: channel closed`.
- Trajectory shape: divergent against H0.
- Kill condition: any reproducible normal quit writes an error log.
- Edge: explain the file-creation mechanism and the channel-close emitter.
- Reasoning mode: induction from issue report, 90% for symptom, 70% for reproducibility outside reporter environment.

### H1: Unconditional Main Logger Creates the File

- Hypothesis: `run_app()` always initializes the main flexi_logger file logger, so any warning/error during shutdown writes `mprocs.log` in the working directory.
- Null: `mprocs.log` is controlled by process-log config or created only when process logging is enabled.
- Perturbation: read public source excerpts for `setup_logger()`, CLI logging arguments, and process-log propagation.
- Observation: `setup_logger()` is unconditional in the app startup path; process logging config is separate.
- Trajectory shape: convergent/partial. It explains file creation but not the source of the `channel closed` error.
- Kill condition: a local run with `setup_logger()` disabled still creates `mprocs.log`.
- Edge: run local perturbation disabling main logger; then instrument shutdown logging source.
- Provenance: current source excerpts from GitHub/docs.rs, no git blame available because worktree could not be created and `gh`/network cloning failed. Upstream search found no other visible issue/PR for `mprocs.log` + `channel closed`.
- Reasoning mode: deduction from source excerpts, 78% because exact revision and local build were not verified.

### H2: Benign Shutdown Channel Close Logged as Error

- Hypothesis: during normal quit, a channel closes as part of teardown and a `.log_ignore()` or propagated `Err` records it at `ERROR`.
- Null: the error is a real abnormal shutdown condition that should remain visible.
- Perturbation: inspect source for shutdown-adjacent result logging paths.
- Observation: shutdown-adjacent `.log_ignore()` paths exist, including Unix waiter cleanup; exact emitter remains unknown.
- Trajectory shape: pending.
- Kill condition: instrumentation shows the error comes from a non-shutdown code path or from a real failing process.
- Edge: locate all `log_ignore()` implementations and call sites, reproduce quit, and downgrade only the expected close path.
- Reasoning mode: abduction from error text plus teardown source shape, 55%.

### H3: Main-Process Log Configurability Is the Proper Fix

- Hypothesis: maintainers want a config/CLI option for application logging, not just source-level suppression.
- Null: the issue is best fixed by not logging a benign close as an error; extra config adds unnecessary surface.
- Perturbation: compare issue wording with existing logging config shape.
- Observation: user asks either "can this error be fixed" or "possible to make logging optional/configurable"; existing logging config is process-focused.
- Trajectory shape: pending.
- Kill condition: maintainer convention shows no app-level config knobs or issue is solved by source-level demotion alone.
- Edge: after exact emitter is found, choose smallest convention-matching fix. Prefer suppressing expected shutdown error; add config only if the error source is intentionally retained.
- Reasoning mode: abduction from wording and API surface, 50%.

### H4: Version Drift / Existing Fix Risk

- Hypothesis: issue was reported on v0.8.3, and master/latest 0.9.2 may have changed enough that the bug is gone or has a different source.
- Null: current master still has the same unconditional logger mechanism and shutdown error.
- Perturbation: compare issue version to current public source and search upstream issues/PRs.
- Observation: public source still has unconditional logger; no duplicate issue/PR found by web search; no local run available.
- Trajectory shape: chaotic because version/source/runtime are not aligned.
- Kill condition: local reproduction on current master either reproduces or does not.
- Edge: clone/build/run current master in QA environment when network/worktree access is available.
- Reasoning mode: abduction plus limited deduction, 35%.

## Frontier Edges

| Edge | Experiment | Predicted classification | Cost | Status |
|---|---|---|---|---|
| E1 | Build current master, run a minimal mprocs session, quit, inspect cwd for `mprocs.log`. | Divergent if reproduced; H4 killed. | Medium | blocked: no worktree/network |
| E2 | Patch `setup_logger()` to no-op/log-to-stderr, rerun E1. | Divergent: file disappears, confirming H1. | Low after E1 | blocked |
| E3 | Instrument or grep all `log_ignore()`/`log::error!` paths around quit, rerun E1. | Convergent: exact emitter found for H2. | Medium | blocked |
| E4 | Implement narrow source-level suppression for expected shutdown channel close, verify fail-on-master/pass-with-fix. | Divergent improvement if no `mprocs.log` and normal error logs still work. | Medium | blocked |
| E5 | If E4 cannot be made narrow, add `--no-main-log` or config equivalent following clap/settings conventions. | Oscillatory risk: solves file annoyance but may hide useful diagnostics. | Medium | open |

## Reasoning Mode Table

| Claim | Mode | Confidence | Provenance |
|---|---|---:|---|
| Normal quit creates `mprocs.log` with `ERROR ... channel closed` on reporter's setup. | Induction | 90% | Issue report |
| Main logger is initialized unconditionally in current public source. | Deduction | 82% | GitHub/docs.rs source excerpts |
| Process-log options do not configure the main logger. | Deduction | 80% | README/source excerpts |
| The channel close is benign shutdown noise. | Abduction | 55% | User says everything works; error text fits teardown |
| A narrow source-level suppression is preferable to a broad logging-off flag. | Abduction | 60% | Minimal bug-fix convention; unverified maintainer preference |

## Pruning Log

- P0: "Process logging config creates `mprocs.log`." Killed by source/README distinction: `proc_log` and `--log-*` configure child process logs; `setup_logger()` is separate.
- P1: "This is definitely `UnixProcessesWaiter::uninit()`." Killed to open hypothesis: it is only a plausible shutdown-adjacent source, not proven.
- P2: "Ready to implement." Killed by missing perturbation access: no worktree, no local build, no fail-on-master/pass-with-fix verification.

## Codex/Gemini Review

- Codex CLI exists (`codex-cli 0.130.0`) but `codex exec` failed with `failed to initialize in-process app-server client: Operation not permitted`.
- Gemini skill/tool is unavailable in this session.
- Confidence on surviving abductive claims is downgraded by approximately 10% because structural/adversarial review could not run.

## Halt / Resume

Investigation halted before Phase 5 because perturbation access is required and unavailable. Resume at E1 once a writable checkout of `pvolok/mprocs` exists at the canonical worktree or another writable local path. The highest-leverage next action is reproducing current master and then disabling `setup_logger()` as a local perturbation.
