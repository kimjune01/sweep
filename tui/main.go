// sweep-tui — horizontal action bar for the two pipeline-wide flags.
//
// One line, two toggles, one link. The CLI (`sweep dry on/off`, `sweep
// pause on/off`) and direct fs touches at ~/.sweep/control/ write the
// same files; this TUI is the live keyboard surface for operators who
// want to flip flags without leaving their cockpit.
//
// Deliberately thin: no embedded `sweep floor` view. Polls the flag
// dir every 5s so external CLI flips become visible without keypress.
// Per-item kanban actions are roadmapped — see ROADMAP.md.
package main

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

const (
	dryFlag      = "dry"
	pauseFlag    = "paused"
	floorCmd     = "sweep"
	floorArg     = "floor"
	refreshEvery = 5 * time.Second
)

// controlDirPath is resolved once at startup. If $HOME can't be found,
// main() bails before constructing the model — the TUI must read from
// the same directory the CLI writes to, or it silently disagrees about
// where the flags live and operator clicks vanish into ./.sweep/.
var controlDirPath string

func flagPath(name string) string { return filepath.Join(controlDirPath, name) }

func flagOn(name string) bool {
	_, err := os.Stat(flagPath(name))
	return err == nil
}

func setFlag(name string, on bool) error {
	if on {
		if err := os.MkdirAll(controlDirPath, 0o755); err != nil {
			return err
		}
		f, err := os.OpenFile(flagPath(name), os.O_CREATE|os.O_WRONLY, 0o644)
		if err != nil {
			return err
		}
		return f.Close()
	}
	err := os.Remove(flagPath(name))
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	return err
}

// --------------- styles
//
// Two visual states per toggle: ON is bright + bold so the eye picks it
// up across the bar; OFF is dim so an idle cockpit reads quiet. The
// keybinding glyph stays normal weight so the action is always legible.
//
// Chewy TUI: "adaptive colors over hardcoded ANSI." Each color is an
// AdaptiveColor so the bar stays legible on iTerm2 Solarized Light *and*
// default xterm dark. Lip Gloss / termenv handle OSC 11 background
// detection automatically and pick the right side. Lip Gloss also
// honors NO_COLOR by dropping styling on the floor — no extra wiring
// needed here. The 256-color codes downsample cleanly to the nearest
// 16-color slot on TERM=xterm.
var (
	dimColor = lipgloss.AdaptiveColor{Light: "240", Dark: "8"}  // off-state border + hints
	onColor  = lipgloss.AdaptiveColor{Light: "166", Dark: "11"} // on-state border + label (orange on light, yellow on dark)
	keyColor = lipgloss.AdaptiveColor{Light: "27", Dark: "6"}   // keybinding glyph

	itemBox = lipgloss.NewStyle().
		Padding(0, 2).
		Border(lipgloss.RoundedBorder()).
		BorderForeground(dimColor)
	itemBoxOn = itemBox.Copy().
			BorderForeground(onColor).
			Foreground(onColor).
			Bold(true)
	keyStyle  = lipgloss.NewStyle().Foreground(keyColor).Bold(true)
	hintStyle = lipgloss.NewStyle().Foreground(dimColor)
)

// --------------- model
//
// flag values are snapshotted into the model on each tick / keypress so
// View() reads from a consistent set even if the filesystem flips
// mid-render. The snapshot is also the place where CLI flips become
// visible: `tickMsg` fires every refreshEvery, re-stats both flags, and
// triggers a re-render only if the values changed (cheap, no flicker).

type model struct {
	dryOn   bool
	paused  bool
	status  string // last message under the bar (action feedback or floor-launch failure)
}

type tickMsg time.Time
type statusMsg string

func tick() tea.Cmd {
	return tea.Tick(refreshEvery, func(t time.Time) tea.Msg { return tickMsg(t) })
}

func snapshot() model {
	return model{dryOn: flagOn(dryFlag), paused: flagOn(pauseFlag)}
}

func (m model) Init() tea.Cmd { return tick() }

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.KeyMsg:
		switch msg.String() {
		case "q", "ctrl+c":
			return m, tea.Quit
		case "r":
			// Manual refresh. The 5s ticker covers the common case;
			// `r` is for operators who flipped a flag via CLI and want
			// to see it immediately.
			s := snapshot()
			s.status = m.status
			return s, nil
		case "d":
			next := !m.dryOn
			if err := setFlag(dryFlag, next); err != nil {
				m.status = fmt.Sprintf("dry toggle failed: %v", err)
			} else {
				m.dryOn = next
				m.status = ""
			}
			return m, nil
		case "p":
			next := !m.paused
			if err := setFlag(pauseFlag, next); err != nil {
				m.status = fmt.Sprintf("pause toggle failed: %v", err)
			} else {
				m.paused = next
				m.status = ""
			}
			return m, nil
		case "f":
			// Shell out to `sweep floor` with the alt screen released
			// so glow's pager owns the terminal. ExecProcess restores
			// our screen on return. The subprocess inherits CWD; floor
			// reads only from ~/.sweep/ so CWD doesn't matter.
			return m, tea.ExecProcess(exec.Command(floorCmd, floorArg), func(err error) tea.Msg {
				if err != nil {
					return statusMsg(fmt.Sprintf("sweep floor exited: %v", err))
				}
				return statusMsg("")
			})
		}

	case tickMsg:
		s := snapshot()
		s.status = m.status
		return s, tick()

	case statusMsg:
		m.status = string(msg)
		return m, nil
	}
	return m, nil
}

func (m model) View() string {
	dryLabel := fmt.Sprintf("%s dry %s",
		keyStyle.Render("d"), flagBadge(m.dryOn, "🌵"))
	pauseLabel := fmt.Sprintf("%s pause %s",
		keyStyle.Render("p"), flagBadge(m.paused, "🚦"))
	floorLabel := fmt.Sprintf("%s floor ↗", keyStyle.Render("f"))

	bar := lipgloss.JoinHorizontal(
		lipgloss.Top,
		boxFor(m.dryOn, dryLabel),
		"  ",
		boxFor(m.paused, pauseLabel),
		"  ",
		itemBox.Render(floorLabel),
	)

	hint := hintStyle.Render(fmt.Sprintf("%s refresh   %s quit   flags live at %s",
		keyStyle.Render("r"), keyStyle.Render("q"), controlDirPath))

	out := bar + "\n" + hint
	if m.status != "" {
		out += "\n" + hintStyle.Render(m.status)
	}
	return out + "\n"
}

// Chewy TUI "len(s) is a bug": every label here is a literal so byte
// length and cell width agree. If a future change feeds user-supplied
// strings into a box, use go-runewidth (already an indirect dep via
// charm) to size — `len(s)` will undercount CJK and emoji and overflow
// the border.
func boxFor(on bool, label string) string {
	if on {
		return itemBoxOn.Render(label)
	}
	return itemBox.Render(label)
}

// Chewy TUI "emoji width": macOS Terminal.app and some tmux setups
// measure 🌵/🚦 as 1 cell instead of 2. Trailing space pads defensively
// so the right edge of the box doesn't shift when the flag flips. The
// glyph stays in both states; the OFF form pads to match cell-count.
func flagBadge(on bool, glyph string) string {
	if on {
		return fmt.Sprintf("%s  ON", glyph)
	}
	return fmt.Sprintf("%s OFF", glyph)
}

// renderOnce prints View() once and exits. Used by the test harness to
// exercise lipgloss styling under varying TERM / NO_COLOR without
// needing a PTY for the Bubble Tea event loop. Reads flag state at
// call time so the rendered output matches what an operator would see.
func renderOnce() {
	fmt.Print(snapshot().View())
}

func resolveControlDir() error {
	home, err := os.UserHomeDir()
	if err != nil {
		return fmt.Errorf("could not resolve home directory: %w", err)
	}
	controlDirPath = filepath.Join(home, ".sweep", "control")
	return nil
}

func main() {
	if err := resolveControlDir(); err != nil {
		// Data integrity: the CLI uses Path.home() which raises on
		// unresolvable home. Match that behavior — silently writing
		// flags to ./.sweep/ would leave the operator clicking buttons
		// that no pipeline actor ever sees.
		fmt.Fprintln(os.Stderr, "sweep-tui:", err)
		os.Exit(1)
	}
	if len(os.Args) > 1 && os.Args[1] == "render" {
		renderOnce()
		return
	}
	// tea.NewProgram options, mapped to Chewy TUI heuristics:
	//
	//   • NO tea.WithAltScreen() — "alt screen vs inline": this is a
	//     thin one-line bar, not a fullscreen view. Stay inline so the
	//     terminal scrollback keeps the operator's prior output. If a
	//     future change wants quit-to-restore behavior, mode ?1049 is
	//     the option to add — not ?47.
	//
	//   • NO mouse / bracketed-paste options yet. When mouse arrives,
	//     use tea.WithMouseCellMotion (DEC mode ?1006), not ?1000. When
	//     a paste target arrives, enable bracketed paste (?2004).
	//
	//   • NO tea.WithoutSignalHandler — Bubble Tea's default routes
	//     Ctrl-C back to SIGINT so backgrounded sessions can be killed
	//     normally. The "ctrl+c" case in Update is belt-and-suspenders.
	//
	//   • Synchronized Output (DEC mode ?2026) is emitted by Bubble
	//     Tea's standard renderer in v1.2+ — no flag needed. The bar
	//     should not tear under the `r`/`d`/`p` keypress refresh or
	//     the 5s ticker re-render.
	//
	//   • isatty extends past color: if stdin/stdout isn't a TTY (e.g.
	//     `sweep-tui | cat`), Bubble Tea opens /dev/tty, fails cleanly,
	//     and we print the error to stderr and exit 1 below.
	p := tea.NewProgram(snapshot())
	if _, err := p.Run(); err != nil {
		fmt.Fprintln(os.Stderr, "sweep-tui:", err)
		os.Exit(1)
	}
}
