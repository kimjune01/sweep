// sweep-tui — horizontal action bar for the two pipeline-wide flags.
//
// One line, two toggles, one link. The CLI (`sweep dry on/off`, `sweep
// pause on/off`) and direct fs touches at ~/.sweep/control/ write the
// same files; this TUI is the live keyboard surface for operators who
// want to flip flags without leaving their cockpit.
//
// Deliberately thin: no embedded `sweep floor` view, no refresh loop.
// Per-item kanban actions are roadmapped — see ROADMAP.md.
package main

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

const (
	dryFlag    = "dry"
	pauseFlag  = "paused"
	floorCmd   = "sweep"
	floorArg   = "floor"
)

func controlDir() string {
	home, err := os.UserHomeDir()
	if err != nil {
		home = "."
	}
	return filepath.Join(home, ".sweep", "control")
}

func flagPath(name string) string { return filepath.Join(controlDir(), name) }

func flagOn(name string) bool {
	_, err := os.Stat(flagPath(name))
	return err == nil
}

func setFlag(name string, on bool) error {
	if on {
		if err := os.MkdirAll(controlDir(), 0o755); err != nil {
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
	dimColor = lipgloss.AdaptiveColor{Light: "240", Dark: "8"}   // off-state border + hints
	onColor  = lipgloss.AdaptiveColor{Light: "166", Dark: "11"}  // on-state border + label (orange on light, yellow on dark)
	keyColor = lipgloss.AdaptiveColor{Light: "27", Dark: "6"}    // keybinding glyph

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

type model struct {
	status string // last message under the bar (action feedback or floor-launch failure)
}

func (m model) Init() tea.Cmd { return nil }

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.KeyMsg:
		switch msg.String() {
		case "q", "ctrl+c":
			return m, tea.Quit
		case "d":
			next := !flagOn(dryFlag)
			if err := setFlag(dryFlag, next); err != nil {
				m.status = fmt.Sprintf("dry toggle failed: %v", err)
			} else {
				m.status = ""
			}
			return m, nil
		case "p":
			next := !flagOn(pauseFlag)
			if err := setFlag(pauseFlag, next); err != nil {
				m.status = fmt.Sprintf("pause toggle failed: %v", err)
			} else {
				m.status = ""
			}
			return m, nil
		case "f":
			// Shell out to `sweep floor` with the alt screen released
			// so glow's pager owns the terminal. ExecProcess restores
			// our screen on return.
			return m, tea.ExecProcess(exec.Command(floorCmd, floorArg), func(err error) tea.Msg {
				if err != nil {
					return statusMsg(fmt.Sprintf("sweep floor exited: %v", err))
				}
				return statusMsg("")
			})
		}

	case statusMsg:
		m.status = string(msg)
		return m, nil
	}
	return m, nil
}

type statusMsg string

func (m model) View() string {
	dryLabel := fmt.Sprintf("%s dry %s",
		keyStyle.Render("d"), flagBadge(dryFlag, "🌵"))
	pauseLabel := fmt.Sprintf("%s pause %s",
		keyStyle.Render("p"), flagBadge(pauseFlag, "🚦"))
	floorLabel := fmt.Sprintf("%s floor ↗", keyStyle.Render("f"))

	bar := lipgloss.JoinHorizontal(
		lipgloss.Top,
		boxFor(dryFlag, dryLabel),
		"  ",
		boxFor(pauseFlag, pauseLabel),
		"  ",
		itemBox.Render(floorLabel),
	)

	hint := hintStyle.Render(fmt.Sprintf("%s quit   flags live at %s",
		keyStyle.Render("q"), controlDir()))

	out := bar + "\n" + hint
	if m.status != "" {
		out += "\n" + hintStyle.Render(m.status)
	}
	return out + "\n"
}

func boxFor(name, label string) string {
	if flagOn(name) {
		return itemBoxOn.Render(label)
	}
	return itemBox.Render(label)
}

func flagBadge(name, glyph string) string {
	if flagOn(name) {
		return fmt.Sprintf("%s ON", glyph)
	}
	return "OFF"
}

func main() {
	p := tea.NewProgram(model{})
	if _, err := p.Run(); err != nil {
		fmt.Fprintln(os.Stderr, "sweep-tui:", err)
		os.Exit(1)
	}
}
