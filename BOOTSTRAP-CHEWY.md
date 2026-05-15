# Bootstrap — Chewy TUI pass on sweep-tui

Paste this into a fresh Claude Code session at `~/Documents/sweep` on branch `temporal-pipeline`. Self-contained.

---

## Context

`sweep-tui` is the operator surface for the dry/pause controls — a thin Bubble Tea horizontal action bar at `tui/main.go`, built to `bin/sweep-tui`. Shipped in commit `f7b599a` ("tui: bubble tea action bar"). It works, but it was built quickly and without auditing against the published TUI design conventions.

The blog post [Chewy TUI](https://june.kim/chewy-tui) catalogs those conventions in one place: Charm as authority, prose IR throughout the substrate, plus a palette of named heuristics (overwrite-don't-clear, Synchronized Output `?2026`, adaptive colors over hardcoded ANSI, OSC 11 background detection, mouse mode `?1006` not `?1000`, alt screen `?1049` not `?47`, `isatty()` extends past color, `NO_COLOR` as a contract) and pitfalls (emoji ZWJ width, `len(s)` is a bug, ESC vs Alt timing, hardcoded ANSI on the other theme, raw mode hijacks Ctrl-C).

This bootstrap is the audit pass: walk the current `tui/main.go` against the Chewy TUI palette and pitfalls, fix what's broken or fragile, and improve adjacent code along the way when it's load-bearing for the same operator experience. The end state is a sweep-tui that survives `NO_COLOR`, light terminals, weird emulators, and the standard set of operator quirks that Charm/Textualize have already written down.

The post is the spec; this bootstrap is the implementation pass. If the post and the current code disagree, the code is wrong.

## Scope

Audit `tui/main.go` against each item in the Chewy TUI palette and pitfalls. For each, either confirm the current code already complies, fix it, or document a deferred decision in `ROADMAP.md` if it requires non-trivial work outside this pass. Commit messages should reference the specific heuristic by name so the diff history maps back to the post.

### A. Palette compliance

1. **Auto-downsample color profiles** (termenv via Lip Gloss). Confirm the current Lip Gloss color choices (`"8"`, `"11"`, `"6"` ANSI indexes) survive on a 16-color terminal. Test under `TERM=xterm`, `TERM=xterm-256color`, and `TERM=screen`. If anything washes out, swap to the closest `lipgloss.Color` that downsamples cleanly.

2. **Adaptive colors over hardcoded ANSI.** The current footer uses bright yellow on dim gray. Verify those render on light terminals; if not, convert to `lipgloss.AdaptiveColor{Light: "X", Dark: "Y"}`. The bar should be legible on iTerm2 Solarized Light *and* on a default xterm dark.

3. **OSC 11 background detection.** `termenv.HasDarkBackground()` queries the terminal via OSC 11. If the adaptive-color migration above happens automatically through Lip Gloss, no work needed; if not, query explicitly and pick palette manually at startup.

4. **Synchronized Output, DEC mode `?2026`.** Bubble Tea v1.2+ may not enable Synchronized Output by default. Check the renderer's capability detection in `tui/go.sum` versions and add the flag if necessary; the bar should not tear during the `r` refresh handler.

5. **Alt screen vs inline.** The current TUI does NOT use the alt screen (deliberately — it's a thin bar, not a fullscreen view). Confirm this is right. If we ever want quit-to-restore behavior, `tea.WithAltScreen()` is the move. Document the decision in a comment so the next session doesn't flip it accidentally.

6. **`NO_COLOR` contract.** Honor `NO_COLOR=1` by dropping all styling and rendering a plain-text bar. Lip Gloss should handle this automatically via termenv; verify with `NO_COLOR=1 ./bin/sweep-tui`.

7. **`isatty()` extends past color.** If `sweep-tui` is piped (`./bin/sweep-tui | cat`), Bubble Tea should detect non-TTY stdin/stdout and bail cleanly with a stderr message rather than spewing escape codes. Verify.

8. **Mouse and bracketed paste.** Currently N/A (no mouse handlers, no paste targets). If a future change adds mouse, use mode `?1006` not `?1000`. If a paste target is added, enable `?2004`. Document this in a comment near the `tea.NewProgram` call.

### B. Pitfalls

1. **Emoji width.** The bar uses 🌵 and 🚦. Verify alignment under macOS Terminal.app (notoriously bad at emoji width), iTerm2, Ghostty, and tmux-inside-tmux. If alignment breaks, pad defensively with a trailing space or swap to a non-emoji glyph that always measures 1 cell.

2. **Raw mode hijacks Ctrl-C.** Confirm `tea.NewProgram` routes Ctrl-C back to SIGINT (Bubble Tea does this by default with `tea.WithoutSignalHandler` *not* set). The current `case "ctrl+c"` is belt-and-suspenders; keep it but make sure SIGINT also works for users who background the process.

3. **Hardcoded ANSI on the other theme.** Covered by item A.2.

4. **Redrawing flickers.** The current TUI redraws on every keypress. With three boxes and ~5 lines of output, this should be invisible — but verify under `tmux` and `screen` where rendering can stutter. If it flickers, enable Synchronized Output (item A.4).

5. **`len(s)` is a bug.** The status messages use `fmt.Sprintf` which is byte-correct but cell-incorrect for unicode. The current bar has no user-supplied strings (all literals), so this is N/A — but flag in a comment near `boxFor` so the next person adding dynamic strings remembers.

6. **ESC vs Alt timing.** Bubble Tea handles ESC-as-key vs Alt-prefix internally. We don't bind Alt anywhere; verify ESC quits cleanly under both fast and slow key delivery (try `ssh sweep@host -o ServerAliveInterval=300` for the slow case).

### C. Adjacent improvements (only when load-bearing)

The bootstrap is scoped to sweep-tui, but if the audit surfaces issues in adjacent code that block proper TUI behavior, fix those too. Examples of acceptable scope creep:

- `sweep floor --plain` formatting if it's the thing the operator pipes into when piping past the TUI.
- `sweep dry status` / `sweep pause status` output format if it conflicts with the TUI's read of the same flag files.
- The `control_state.py` atomic-write pattern if a race condition surfaces during TUI ↔ CLI flag flipping.

Don't bundle unrelated cleanup. If you find prose typos in `README.md` or `ROADMAP.md`, fix them in a separate commit with a `docs:` prefix.

## Acceptance

- `NO_COLOR=1 ./bin/sweep-tui` renders a plain-text bar with no escape codes (verified by piping to a hex dump).
- `./bin/sweep-tui` on a light-theme terminal shows legible text in the same logical color positions as on dark.
- `./bin/sweep-tui | cat` exits non-zero with a stderr message about needing a TTY.
- A six-frame stress test (rapid `d`/`p`/`r` cycling) does not tear under tmux, ghostty, or Terminal.app.
- 🌵 and 🚦 align in the bar across at least three emulators; if not, the bar uses non-emoji glyphs (or pads compensate, with a comment explaining why).
- `tui/main.go` has comments at each `tea.NewProgram` option and each Lip Gloss color declaration that map back to a specific Chewy TUI heuristic by name.
- Commit history has one commit per heuristic (or per logical pair when two heuristics fix the same site), each with a lowercase prefix (`color:`, `paste:`, `mouse:`, `flicker:`, etc.) that maps back to the post.

## Out of scope

- The Wish front door (`ssh sweep@factory` drops you into the TUI). Roadmap'd separately under "Wish front door for remote control."
- Per-PR kanban selection. Roadmap'd separately under "TUI kanban item selection."
- Replacing the Bubble Tea framework with anything else. Charm is authoritative.
- The `sweep floor` cockpit's render shape. That's a separate surface; it pipes markdown, not TUI escape codes.

## Style

- Commit messages: lowercase area prefix that maps to a Chewy TUI heuristic name. Examples: `color: lipgloss adaptive`, `paste: bracketed`, `flicker: synchronized output`, `width: emoji padding`.
- One commit per heuristic, ideally. Bundle when two heuristics edit the same line.
- Don't claim compliance in a commit message unless you verified it. "Verified by `NO_COLOR=1 ./bin/sweep-tui | hexdump`" beats "honors NO_COLOR."
- After the pass, append a "Shipped" entry to ROADMAP.md under the existing "Operator controls + TUI" block: a paragraph summarizing the audit pass and the heuristics now load-bearing.

## How to run the bootstrap

1. Read [Chewy TUI](https://june.kim/chewy-tui) once, end to end.
2. Read `tui/main.go` and `tui/go.mod` once.
3. Work through Section A items in order. For each, either confirm-with-evidence, fix, or defer-with-roadmap-note. Commit after each substantive change.
4. Work through Section B items the same way.
5. Run the full acceptance checklist. Re-test the items that worried you the first time.
6. Append the Shipped paragraph to ROADMAP.md. Final commit.

If the audit takes more than a day, you're doing it wrong. The bar is ~250 LOC; most items are five-minute verifications.
