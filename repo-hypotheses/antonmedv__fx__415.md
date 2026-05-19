# Hypothesis Graph: antonmedv/fx#415

Target: antonmedv/fx issue #415, "Piping any stdout from node.js to fx stdin causes non-functional UI state"
Date: 2026-05-18 (second pass, full perturbation access)
Mode: standalone investigate. Halts at tissue-class outcome (no PR).

## Issue Recap

Reporter command:

```sh
node -e 'process.stdout.write(JSON.stringify({"a":1}))' | fx
```

Observed by reporter on macOS Tahoe and Ubuntu 22 LTS with Homebrew `fx` v39.2.0:
- TUI renders the JSON
- Keypresses echo at the bottom of the screen; UI does not respond
- Workaround: `... > test.json && cat test.json | fx` reportedly works
- Maintainer (antonmedv) cannot reproduce: "tested on windows and macos. seems works for me."

## Environment

`sweep project-info antonmedv/fx` returns `docker:sweep-tester:latest`. Worktree was created at `/Users/junekim/.sweep/worktrees/antonmedv__fx` (master HEAD ef13a31f-ish, fx v39.2.0+ with bubbletea v1.3.6). Local `go build` succeeds.

## Round 2 Experiments (new evidence)

### E1 — Read syscall behavior of node-pipe vs cat-pipe

Built a tiny Go reader that does `os.Stdin.Read(buf)` in a loop and prints `(n, err)`. Tested both producers:

```
node | reader  → Read#0: n=7 err=<nil>  data="{\"a\":1}"
                 Read#1: n=0 err=EOF    data=""
cat  | reader  → Read#0: n=7 err=<nil>  data="{\"a\":1}"
                 Read#1: n=0 err=EOF    data=""
```

Identical at the syscall level. Trajectory: **convergent against** the "node-vs-cat is a kernel/pipe-level distinction" framing. Whatever the reporter observed, it is not visible in the io.Reader contract.

### E2 — Bubble Tea v1.3.6 auto-fallback to /dev/tty

Read `bubbletea@v1.3.6/tea.go:553-589` and `tty_unix.go`. In `defaultInput` mode, Bubble Tea checks whether `os.Stdin` is a terminal; when it is not, it calls `openInputTTY()` (= `os.Open("/dev/tty")`) and swaps `p.input` to the new TTY file. `initInput` then puts the TTY into raw mode.

This means fx's current `tea.NewProgram(m, tea.WithAltScreen(), withMouse, tea.WithOutput(os.Stderr))` should already cause Bubble Tea to read keys from `/dev/tty`, not from the piped stdin. `tea.WithInputTTY()` would route through the same `openInputTTY()` call.

Reasoning mode: deduction from library source. Confidence 90%.

**This kills H1/H3 from the prior pass.** The earlier graph proposed adding `tea.WithInputTTY()`, but in Bubble Tea v1.3.6 that is equivalent to the default path for piped stdin.

### E3 — Empirical test: does the fix shape change anything?

Built two binaries:
- `fx-test`: current master (no fix)
- `fx-fix`: master + `tea.WithInputTTY()` added to `tea.NewProgram`

Drove both with `expect` and a Python `pty.openpty()` harness:
- Spawn fx under a real PTY (slave is fx's controlling terminal)
- fx's stdin = anonymous pipe carrying `JSON.stringify({"a":1})` from node
- Wait ~2s, send `q`, see whether fx exits

Result (both producers, both binaries): fx renders to alt-screen but `q` is not handled. Both binaries hang.

But: the same hang occurs when fx's stdin is `/dev/tty` (no pipe at all, run via `expect spawn /tmp/fx-fix`). This means the hang is **not** the reported bug; it is the test harness failing to answer termenv's color/cursor OSC queries (`\x1b]11;?\x07` and `\x1b[6n`). Bubble Tea / termenv waits for those responses and the synthetic PTY never delivers them, so the keypress codepath is never exercised in this harness.

Trajectory: **chaotic** for the question "does WithInputTTY fix the bug?" The harness cannot distinguish a fix from a no-fix because it does not reach the input loop. Decompose differently.

Reasoning mode: induction from harness runs. The induction kills the harness, not the hypothesis.

### E4 — Provenance / first-mover check

- `git blame main.go` on `tea.NewProgram(...)` shows the construction has been stable across releases; no commit removed a prior `WithInputTTY()`.
- `gh pr list` and `gh issue list` searches surface no parallel work on this issue. Maintainer comment on #415 dismisses the report ("seems works for me").
- Operator PR history: #414 (merged) was an adjacent stdin-detection fix for /dev/null in launch agents; orthogonal to this issue.

## Where this leaves things

What is verified:
- Bubble Tea v1.3.6 already opens `/dev/tty` for input when stdin is non-TTY.
- `tea.WithInputTTY()` would route through the same code path; it is not a meaningful change.
- The node-vs-cat distinction in the reporter's description has no support in the io.Reader contract.

What is not verified:
- The actual bug behavior in a real interactive terminal (macOS Tahoe / Ubuntu 22 LTS Homebrew install). The local harnesses cannot exercise the input loop because of termenv OSC-query hangs.
- Whether the reporter's environment exposes a different failure mode (terminal emulator, shell, locale, login-shell vs subshell, controlling-tty assignment) that Bubble Tea's `openInputTTY()` does not handle.

What does not survive:
- Hypothesis "the fix is `tea.WithInputTTY()`" — E2 plus the v1.3.6 source kills it.

## Updated Graph State

| Node | Status | Shape | Notes |
|---|---|---|---|
| H0 | partial-confirmed | divergent | Reporter symptoms acknowledged; no local repro of the *interactive* behavior |
| H1 (Bubble Tea reads pipe as input) | **killed** | convergent against | Library source shows auto-fallback to /dev/tty in v1.3.6 |
| H2 (node vs cat is timing/EOF) | killed | convergent against | E1 shows identical Read trajectory |
| H3 (WithInputTTY is the fix) | **killed** | convergent against | Bubble Tea routes both defaultInput-with-pipe and ttyInput through the same openInputTTY() |
| H4 (terminal-emulator / controlling-tty specific) | open | predicted divergent | Would explain "works for me" from maintainer plus reporter's macOS Tahoe + Ubuntu observation |

## Frontier Edges

| Edge | Experiment | Predicted shape | Notes |
|---|---|---|---|
| H4 | Ask reporter for `TERM`, terminal emulator, shell, and `tty` / `tty -s` output before vs after the node pipe; ask whether `node | fx` from a fresh terminal differs from `node | fx` inside `tmux`/`screen` | divergent if env-specific | Requires reporter cooperation; can be solicited via a tissue comment |
| harness | Build a PTY harness that responds to OSC 10/11 and DSR queries so that the input loop is actually reached; then test fx + `tea.WithInputTTY()` head-to-head | divergent if there is a difference | Useful research, but unlikely to flip the verdict on the proposed fix because E2 already shows the code paths are equivalent |

## Outcome

**Tissue-class.** No code change is justified by the evidence.

- The most-cited candidate fix (`tea.WithInputTTY()`) is a no-op given Bubble Tea v1.3.6's auto-fallback. Shipping it would be cargo-cult, and the maintainer has already declined to engage with the issue.
- The actual reporter behavior cannot be reproduced in the operator's environment. The maintainer also reports non-reproduction.
- The clean next step is a tissue comment that reports the diagnostic findings (Read-level parity, Bubble Tea auto-fallback) and requests environment specifics from the reporter. Posting that is the operator's call, not the substrate's.

Halt reason: frontier reduces to "ask the reporter," which is human-attendable. No PR readiness record written.

## Reasoning Mode Summary

| Claim | Mode | Confidence |
|---|---|---|
| node-pipe and cat-pipe deliver identical Read traces | induction (run twice with the same harness) | 95% |
| Bubble Tea v1.3.6 opens /dev/tty for input when stdin is a non-TTY File | deduction from library source | 90% |
| `tea.WithInputTTY()` would not change behavior here | deduction from library source | 85% |
| The bug is real but environment-specific in a way the operator cannot reproduce | abduction | 60% |

## Pruning Log

- H1 (prior pass) — killed by E2 (library source review).
- H2 (prior pass) — killed by E1 (Read trajectory parity).
- H3 (prior pass) — killed by E2/E3 (code-path equivalence; harness cannot validate but the deduction is independent).

---

## Round 3 (2026-05-19) — bug reproduced and fixed

Round 2's "tissue-class, environment-specific" verdict was wrong. The Python
PTY harness in that round failed at OSC 10/11 / DSR queries, so it never
reached the input loop and could not distinguish a working fx from a broken
one. Round 3 builds a PTY harness that answers those queries.

### E5 — Better PTY harness

`/tmp/fx-ptytest.py`: `pty.fork()` runs the child command, parent loop reads
output and replies to `\x1b]11;?…`, `\x1b[6n`, primary DA, and DECRQM queries
so bubbletea proceeds. After ~1.5 s the parent sends `j` (down) then `q`
(quit) and waits for child exit.

```
file: 'j' produces 35 bytes of status-bar update, 'q' exits status=0
cat:  'j' produces 26 bytes of status-bar update, 'q' exits status=0
node: 'j' produces 1 byte (literal 'j' echo), 'q' is not consumed, child hangs
```

Bug deterministically reproduces. Round 2's "harness can't drive the loop"
was a harness limitation, not a real environmental constraint.

### E6 — Termios poll during program lifetime

Added a 50 ms termios poller to fx (logged to `/tmp/fx-debug.log`) and re-ran
each mode:

```
cat case (working):
  tick=0  Iflag=0x2800   Lflag=0x20000043  ICANON=false ECHO=false  ← raw
  tick=1  Iflag=0x2800   Lflag=0x43        ICANON=false ECHO=false  ← raw, EXTPROC dropped
  (stays raw thereafter)

node case (broken):
  tick=0  Iflag=0x2800   Lflag=0x20000043  ICANON=false ECHO=false  ← raw, as expected
  tick=1  Iflag=0x2b02   Lflag=0x200005cb  ICANON=true  ECHO=true   ← cooked, FLIP
  (stays cooked thereafter)
```

Trajectory: divergent. fx enters raw mode in both cases, but in the node
case **the tty is reverted to cooked mode within ~50 ms after fx initialized**.

### Diagnosis (H₅)

Node opens `process.stdin` via libuv's `uv_tty_init`. When fd 0 is a TTY (it
is — node inherited the shell's tty), libuv saves the current termios so it
can restore it on shutdown (this is the "tty-aware program" pattern: clean
up after yourself when you exit). When `node -e '…'` exits, libuv's tty
close path runs and `tcsetattr`s the tty back to its saved (cooked) state.

`cat` never opens a tty wrap, so cat's exit is termios-neutral.

The process tree:

1. shell holds tty in cooked mode
2. shell forks node and fx into the same job pgrp
3. fx starts, bubbletea opens `/dev/tty` and calls `term.MakeRaw` (tty → raw)
4. node finishes writing its JSON, libuv shutdown runs `tcsetattr` (tty →
   cooked)
5. node closes its end of the pipe; fx parser sees EOF
6. fx is now running with the tty in cooked mode; bubbletea's cancelreader
   is select-waiting on `/dev/tty` but the kernel line-buffers input until
   Enter and echoes it — exactly matches the reporter's "key presses are
   rendered at the bottom of the screen"

Order of events at process exit is well-defined: libuv's handle cleanup
(including tty restore) happens during `_exit()` cleanup before the kernel
closes file descriptors. So pipe EOF on the reader side arrives **after**
the termios restore. fx can therefore detect the right moment to re-init
the terminal by listening for stdin EOF.

### Fix

`main.go` parser goroutine, EOF branch:

```go
if err == io.EOF {
    // If the upstream pipe writer (e.g. node, which uses libuv) had
    // the controlling tty open, its exit cleanup will tcsetattr the
    // tty back to its saved (cooked) state, undoing the raw mode
    // bubbletea installed at startup. Pipe EOF arrives after that
    // restore, so re-init the terminal here to put raw mode back.
    _ = p.RestoreTerminal()
    p.Send(eofMsg{})
    break
}
```

`p.RestoreTerminal()` is bubbletea's documented re-init hook (used by SIGCONT
after suspend). It calls `initTerminal` → `MakeRaw` and re-creates the
cancelreader. Idempotent in the cat/file cases where termios was not
disturbed; corrective in the node case.

### Verification

| Mode | Before fix | After fix |
|------|-----------|-----------|
| `fx file.json` | works | works |
| `cat file.json \| fx` | works | works |
| `node -e '…' \| fx` | broken | works |

`go test ./...` — all green.

### Provenance update

- The race exists for any bubbletea program that reads piped input from a
  tty-aware writer. Not a recent regression — present since bubbletea v1's
  default-tty-fallback was wired in.
- Searched charmbracelet/bubbletea issues: no existing fix or option to
  re-init on EOF. The fix has to be in fx.
- Maintainer's "works for me" likely reflects a terminal emulator + shell
  combo that masks the late-arriving cooked-mode flip (some emulators
  re-flush pending input on a focus event or window resize). The PTY harness
  reproduces deterministically.

### Updated graph state

| Node | Status | Shape | Notes |
|---|---|---|---|
| H4 (env-specific, Round 2) | killed | — | Superseded by H5; reproducible without env quirks |
| H5 (libuv tty restoration race) | confirmed | divergent | Termios poll caught the flip in node case only |

### Outcome (revised)

**Fix-class.** PR-ready. One-line addition to the EOF branch.
