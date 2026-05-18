# Hypothesis Graph: antonmedv/fx#415

Target: antonmedv/fx issue #415, "Piping any stdout from node.js to fx stdin causes non-functional UI state"
Date: 2026-05-18
Mode: standalone investigate, halted before code because perturbation access is missing.

## Environment

`sweep project-info antonmedv/fx`:

```json
{
  "repo": "antonmedv/fx",
  "worktree": "/Users/junekim/.sweep/worktrees/antonmedv__fx",
  "worktree_exists": false,
  "test_env": "docker:sweep-tester:latest",
  "test_cmd": null,
  "test_setup_cmd": null
}
```

Local constraints:

- Cannot create the canonical worktree: sandbox denies writes under `/Users/junekim/.sweep/worktrees`.
- Cannot clone into the shared workspace: shell DNS cannot resolve `github.com`.
- `gh issue view` cannot reach `api.github.com`.
- No local `fx` binary is installed.
- `codex exec` exists but cannot initialize in this sandbox (`Operation not permitted`).
- `gemini` exists, but no local fix diff or full graph can be validated with source-level perturbations yet.

Perturbation access status: blocked for source edits, test execution, and behavioral reproduction. Only cached issue data and web-read source/documentation were available.

## Issue Evidence

Reporter command:

```sh
node -e 'process.stdout.write(JSON.stringify({"a":1}))' | fx
```

Observed behavior from issue #415:

- TUI displays the JSON.
- Interactivity is non-functional.
- Keypresses are rendered at the bottom of the screen and overwrite the status/path area.
- Reproduced by reporter on macOS Tahoe and Ubuntu 22 LTS with Homebrew `fx` v39.2.0.
- Workaround reported by user:

```sh
node -e 'process.stdout.write(JSON.stringify({"a":1}))' > test.json && cat test.json | fx
```

This issue was still open on GitHub on 2026-05-18. No linked development branch or PR was shown in the GitHub issue page.

## Blind-Blind Merge

### Hypothesis A

Root cause: `fx` consumes JSON from `stdin`, then starts Bubble Tea without changing Bubble Tea's input source. Bubble Tea defaults to reading key events from `stdin`; when `stdin` is still the producer pipe rather than the controlling terminal, keypresses are not delivered to the TUI as `tea.KeyMsg`. The terminal then echoes typed bytes in the visible output area.

Fix shape: in interactive TUI mode after piped input, start Bubble Tea with `tea.WithInputTTY()` so Bubble Tea opens the controlling TTY for key input while keeping `tea.WithOutput(os.Stderr)`.

Evidence:

- GitHub source for `main.go` shows `src = os.Stdin` for piped input, then interactive mode constructs `tea.NewProgram(m, tea.WithAltScreen(), withMouse, tea.WithOutput(os.Stderr))`.
- Bubble Tea docs state `WithInput` defaults to stdin and `WithInputTTY()` opens a new TTY for input.

Confidence: 70% abduction, capped because no local binary/worktree exists and the Node-vs-cat distinction remains unexplained.

### Hypothesis B

Root cause: `fx` reads piped JSON from `os.Stdin`, then starts Bubble Tea without an explicit input source. Bubble Tea defaults UI input to stdin, but in the pipe case stdin is still the pipe, not the terminal. The TUI renders, but keypresses typed in the terminal are not read by Bubble Tea and appear at the bottom instead.

Fix shape: when stdin is a pipe and `fx` enters interactive Bubble Tea mode, create the program with terminal input explicitly, likely by adding `tea.WithInputTTY()` while keeping `tea.WithOutput(os.Stderr)`.

Concrete perturbation: patch only Bubble Tea program construction to add `tea.WithInputTTY()`, then rerun the Node-pipe repro and verify keypresses drive the UI.

Confidence: 70% abduction, with the same unresolved caveat that the reported `cat test.json | fx` workaround needs direct timing/EOF classification.

### Where A and B Diverge

No material divergence. Both independent passes converge on stdin ownership/input-source misbinding and on `tea.WithInputTTY()` as the minimal fix shape. The shared uncertainty is the Node-vs-cat contrast: it may be timing/EOF/newline-specific, or it may be reporter-environment noise around the same underlying stdin ownership bug.

Downstream implication: proceed at higher confidence once a checkout exists, but make the first perturbation classify the producer matrix (`node`, `printf`, `cat`, newline/no-newline) before claiming a fully general fix.

## Graph State

| Node | Status | Shape | Summary |
|---|---|---|---|
| H0 | partial | divergent from expected TUI behavior | Issue report says JSON renders but keys are echoed instead of handled. Local reproduction blocked. |
| H1 | partial | convergent source evidence | Bubble Tea likely reads from piped stdin because `tea.NewProgram` has no `WithInputTTY`; blind pushout agreed. |
| H2 | open | predicted divergent | Node-specific pipe timing may leave stdin in a state where Bubble Tea misses terminal input; cat workaround needs direct repro. |
| H3 | open | predicted convergent | `tea.WithInputTTY()` in TUI path should restore key handling without changing parser/output behavior. |

## Nodes

### H0: Baseline observation

Hypothesis: `fx` should accept JSON from any stdout pipe and then run an interactive TUI whose keypresses are read from the user's terminal.

Null: Pipe producer identity should not affect post-parse key handling; Node output and `cat` output should behave identically.

Perturbation:

```sh
node -e 'process.stdout.write(JSON.stringify({"a":1}))' | fx
```

Trajectory:

- Reported sample 1: macOS Tahoe, Homebrew `fx` v39.2.0, JSON renders, keys echo at bottom.
- Reported sample 2: Ubuntu 22 LTS, same behavior.
- Reported contrast: `node ... > test.json && cat test.json | fx` works.
- Local sample: not run; no `fx` binary and no checkout.

Shape: divergent from expected behavior, but partial because the local environment cannot reproduce.

Kill condition: if a local run of v39.2.0 and current master handles Node-piped input correctly under a real PTY, H0 becomes environment-specific and must split by terminal/shell/install path.

Edge: inspect Bubble Tea input source and stdin/TTY routing in interactive mode.

Reasoning mode: induction from reporter samples, confidence 75%.

### H1: Bubble Tea reads the data pipe as keyboard input

Hypothesis: after parsing piped JSON, `fx` starts Bubble Tea with default input, so Bubble Tea reads from `os.Stdin`, which is the JSON pipe, not `/dev/tty`.

Null: Bubble Tea already reopens `/dev/tty` or `fx` supplies another input reader, so the bug must be in renderer/output routing or terminal mode restoration.

Perturbation:

- Source read: inspect `main.go` TUI setup.
- Documentation read: inspect Bubble Tea `ProgramOption` docs.

Trajectory:

- Source shows `src = os.Stdin` for piped input.
- Source shows interactive program options include `tea.WithAltScreen()`, mouse option, and `tea.WithOutput(os.Stderr)`.
- Source does not show `tea.WithInputTTY()` or `tea.WithInput(...)` in the TUI path.
- Bubble Tea docs say default input is stdin; `WithInputTTY()` opens a new TTY for input.

Shape: convergent source evidence.

Kill condition: a full checkout reveals generated/build-tagged platform code or wrapper logic not visible in `main.go` that already replaces Bubble Tea input.

Edge: test a minimal patch adding `tea.WithInputTTY()` under piped-input TUI mode.

Reasoning mode: deduction from source plus library docs, confidence 85%; downgraded because source was web-read and not locally checked out.

### H2: Node-vs-cat distinction is timing or pipe-close behavior

Hypothesis: Node writes JSON without a trailing newline and closes quickly; that pipe state interacts with Bubble Tea's stdin reader differently than `cat test.json | fx`, exposing a timing race between parser goroutine and Bubble Tea input initialization.

Null: Node-vs-cat distinction is incidental reporter environment noise; any piped stdin can fail because Bubble Tea's input source is wrong.

Perturbation:

Under a real PTY with a built `fx`, compare:

```sh
node -e 'process.stdout.write(JSON.stringify({"a":1}))' | ./fx
printf '{"a":1}' | ./fx
printf '{"a":1}\n' | ./fx
cat test.json | ./fx
```

Inject `q`/arrow key events via a PTY harness and classify whether `tea.KeyMsg` is handled or bytes echo.

Predicted shape: oscillatory if only Node/no-newline fails; divergent if all piped-input cases fail.

Kill condition: all producers behave identically before the fix.

Edge: if oscillatory, split newline/EOF/timing from TTY-input-source hypotheses.

Reasoning mode: abduction, confidence 60%.

### H3: `tea.WithInputTTY()` is the minimal fix

Hypothesis: when `fx` enters interactive TUI mode after reading data from stdin, `tea.WithInputTTY()` makes Bubble Tea read keys from the controlling terminal and fixes the echo/non-functional state.

Null: reopening `/dev/tty` is insufficient because the bug is caused by output renderer target, terminal mode setup, or parser goroutine lifecycle.

Perturbation:

Patch TUI program construction to include `tea.WithInputTTY()` for piped-input interactive mode, then run the H2 PTY matrix and the existing Go test suite in the canonical docker environment:

```sh
docker run --rm -v "$(sweep project-info antonmedv/fx --field worktree)":/work -w /work sweep-tester:latest go test ./...
```

Predicted shape: divergent improvement; key events stop echoing and existing tests pass.

Kill condition: patched binary still echoes keys, fails file-mode input, or breaks noninteractive query mode.

Edge: if killed, inspect Bubble Tea output/renderer and terminal mode setup.

Reasoning mode: abduction from library affordance plus deduction from source, confidence 70%.

## Frontier Edges

| Edge | Experiment | Predicted classification | Priority |
|---|---|---|---|
| H0 -> H1 | Local source checkout, inspect exact `main.go` and `go.mod` version of Bubble Tea | convergent | high |
| H1 -> H3 | Patch with `tea.WithInputTTY()` and run PTY key harness | divergent improvement | high |
| H0 -> H2 | Compare Node/printf/cat producers with and without trailing newline | divergent or oscillatory | high |
| H3 -> regression | Run `go test ./...` in `sweep-tester` docker image | convergent pass | medium |
| H3 -> provenance | `git blame main.go` around `tea.NewProgram`; search issues/PRs for `WithInputTTY`, `stdin`, `tty`, `pipe` | convergent risk assessment | medium |

## Reasoning Modes

| Claim | Mode | Confidence |
|---|---|---|
| The reported behavior is real enough to investigate | induction from issue report | 75% |
| `fx` currently passes no explicit Bubble Tea input option in the visible TUI path | deduction from web-read source | 85% |
| Bubble Tea defaults input to stdin and has `WithInputTTY()` for reopening TTY input | deduction from official docs | 95% |
| The likely fix is adding `tea.WithInputTTY()` in interactive piped-input mode | abduction | 70% |
| The Node-vs-cat contrast is timing/newline-related | abduction | 60% |

## Pruning Log

No hypotheses pruned yet. Required local perturbations are blocked.

## Provenance

Not completed. Required commands are blocked by missing checkout/network:

- `git blame main.go` around the `tea.NewProgram` call.
- GitHub issue/PR search for related stdin/TTY/Bubble Tea fixes.
- Existing PR idempotency guard.

Risk assessment from available evidence:

- `tea.WithInputTTY()` is an upstream Bubble Tea API specifically shaped for the suspected failure mode.
- Scope should remain minimal; antonmedv/fx has high maintainer sensitivity to broad or AI-looking diffs.
- The fix must not affect noninteractive query mode (`fx .foo`) because that mode correctly uses stdin as data input and exits without TUI.

## Current Halt

Status: blocked before Phase 5.

Reason: perturbation access is required and currently unavailable. There is no writable checkout, no network clone path, no local `fx` binary, and no ability to run codex filtering. The graph is a valid checkpoint, but not a PR-ready diagnosis.

Next resumption step:

1. Provide or create a writable checkout of `antonmedv/fx`.
2. Re-run `sweep project-info antonmedv/fx` and mirror `test_env`.
3. Reproduce H0 under a PTY.
4. Patch H3 and run the same PTY matrix plus targeted `go test ./...`.
