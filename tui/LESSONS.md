# Lessons from the Chewy TUI audit pass

Notes from auditing `sweep-tui` (Bubble Tea + Lip Gloss action bar, ~180 LOC) against the heuristics in [Chewy TUI](https://june.kim/chewy-tui). Aimed at the next person testing or building a Charm TUI.

## What surprised us

### 1. `NO_COLOR` does not silence terminal *queries*

`termenv` initializes by probing the terminal: OSC 11 (`\x1b]11;?\x1b\\`) for background color, CSI 6n (`\x1b[6n`) for cursor position. Three ESC bytes go out **regardless of `NO_COLOR`**.

`NO_COLOR` suppresses styling (SGR — `CSI ... m`). It does not suppress capability probes. They're how termenv decides which palette to use even when it can't emit color.

**Test implication.** "No escape codes under `NO_COLOR`" is the wrong invariant. The right one is "no SGR under `NO_COLOR`":

```sh
sgr_count() { printf '%s' "$1" | grep -aoE $'\033\\[[0-9;]*m' | wc -l; }
```

Counting raw `\033` will false-fail every time.

### 2. Bare `TERM=xterm` drops to Ascii in lipgloss/termenv

We expected `TERM=xterm` → 16-color ANSI. Reality: `termenv` treats bare `xterm` conservatively and returns `Ascii`. SGR emits only when TERM advertises color explicitly — `xterm-256color`, `screen-256color`, `xterm-kitty`, `tmux-256color`, anything with `-color` / `-256color` / `-direct` in the name.

In practice that means many minimal Linux setups (alpine without `ncurses-terminfo-base`, some CI runners, bare ssh sessions where TERM didn't propagate) get plain boxes. AdaptiveColor still does the right thing on iTerm2 / Ghostty / Terminal.app, which all advertise 256-color, but the "downsample cleanly to 16-color" invariant from the post is really "don't crash and still render the layout" — not "must emit color at every TERM level."

If you want color to survive bare `xterm`, `CLICOLOR_FORCE=1` overrides this. Don't reach for it by default; it lies to termenv about terminal capability.

### 3. The `render` subcommand pattern beats PTY automation

Bubble Tea owns the event loop and needs a real TTY. Testing styling through it means `expect` or `pty.New()` — heavy machinery for an invariant check.

Cleaner: add a `render` subcommand that prints `model{}.View()` once and exits. ~5 lines of code. The styling layer is pure, deterministic, env-var-driven, and a shell harness can grep its bytes.

```go
if len(os.Args) > 1 && os.Args[1] == "render" {
    fmt.Print(model{}.View())
    return
}
```

You still need a PTY for termenv to think it's talking to a terminal. `util-linux script(1)` is the portable wrapper:

```sh
script -qc "/path/to/binary render" /dev/null
```

BSD/macOS script has different syntax (`script -q /dev/null sh -c "..."`). Sniff at runtime if you care about both.

### 4. Pipe behavior is fine, but pipeline exit codes hide it

`./bin/sweep-tui | cat` exits 1 on the TUI side ("could not open a new TTY") and 0 on `cat`. Default shell pipeline exit is the *last* command's, so `$?` reads 0 and a casual test reads "doesn't fail."

Use `${PIPESTATUS[0]}` (bash) or `set -o pipefail`. Or, in the harness: run the binary with stdin redirected from `/dev/null` and check its exit code directly, not in a pipeline.

### 5. Emoji width is real, and asymmetric labels make it worse

🌵 and 🚦 measure 2 cells in spec, 1 cell on macOS Terminal.app and some tmux setups. Lipgloss can't fix this — it asks `go-runewidth`, which trusts the unicode width table, not the terminal's actual measurement.

Defensive fix: trailing space pad, and keep the glyph in *both* ON and OFF states so the right edge of the box doesn't shift on toggle. `"🌵  ON"` / `"🌵 OFF"` survives the misreading because the asymmetry is absorbed by the box auto-sizing on a fixed character count.

## What we'd do differently

- **Anchor heuristic comments at call sites, not in a separate doc.** We littered `tui/main.go` with `// Chewy TUI: X` comments at every `tea.NewProgram` option and color decl. The next person can grep `Chewy TUI` to find every decision and follow it back to the post. A separate "design rationale" file would rot the moment someone refactored a style.

- **Build the test harness before the audit.** We built it after, and twice tightened the invariant (raw ESC → SGR, then SGR-required → SGR-or-render). If the harness had existed first, we'd have caught the termenv probes immediately and not committed a too-strict assertion.

- **Don't claim compliance you didn't verify.** Some Chewy items are interactive (light-theme legibility, tmux flicker, emulator-specific emoji alignment). The right move is "deferred, untested" in the commit message, not "honors X." We did this, and it kept commit history honest.

## Reusable bits

- `tui/test-chewy.sh` — shell invariants harness, runs anywhere with `script(1)`
- `tui/test-chewy.docker.sh` — wraps it in `golang:1.23-alpine` + `util-linux` for a clean environment
- The `render` subcommand idiom — drops into any Charm TUI for headless styling tests

## Pointers

- [Chewy TUI](https://june.kim/chewy-tui) — the palette + pitfalls catalog this audit was a pass against
- `tui/main.go` — grep `Chewy TUI` to find every heuristic anchor
- termenv source for color profile detection: `github.com/muesli/termenv/termenv_unix.go`
