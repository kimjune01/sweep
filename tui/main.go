// sweep-tui — horizontal action bar for the two pipeline-wide flags.
//
// One line, two toggles, one link. The CLI (`sweep dry on/off`, `sweep
// pause on/off`) and direct fs touches at ~/.sweep/control/ write the
// same files; this TUI is the live keyboard surface for operators who
// want to flip flags without leaving their cockpit.
//
// Deliberately thin: no embedded `sweep cockpit` view. Polls the flag
// dir every 5s so external CLI flips become visible without keypress.
// Per-item lanes actions are roadmapped — see ROADMAP.md.
package main

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/glamour"
	"github.com/charmbracelet/glamour/ansi"
	"github.com/charmbracelet/glamour/styles"
	"github.com/charmbracelet/lipgloss"
)

// sweepGlamourStyle picks dark/light from the terminal background,
// then quiets the loudest glamour defaults — no blue-block H1, no
// red code spans, no chunky highlights. The cockpit is a snapshot,
// not a tutorial; we want it scannable, not advertising itself.
// Table separators upgrade to Unicode `│ ─ ┼`. Outer rounded corners
// come from the viewBox wrapper, since glamour disables outer table
// borders explicitly.
func sweepGlamourStyle() ansi.StyleConfig {
	cfg := styles.DarkStyleConfig
	if !lipgloss.HasDarkBackground() {
		cfg = styles.LightStyleConfig
	}

	col := "│"
	row := "─"
	mid := "┼"
	cfg.Table.ColumnSeparator = &col
	cfg.Table.RowSeparator = &row
	cfg.Table.CenterSeparator = &mid

	// H1 → bold text in default foreground; no blue background block.
	cfg.H1.BackgroundColor = nil
	cfg.H1.Color = nil
	cfg.H1.Bold = boolPtr(true)
	// H2/H3/H4 → strip the literal '##'/'###' prefix glamour inserts;
	// bold-only typography carries the heading without the markdown
	// punctuation leaking through to the rendered view.
	empty := ""
	cfg.H2.Prefix = empty
	cfg.H2.BackgroundColor = nil
	cfg.H2.Bold = boolPtr(true)
	cfg.H3.Prefix = empty
	cfg.H3.BackgroundColor = nil
	cfg.H3.Bold = boolPtr(true)
	cfg.H4.Prefix = empty
	cfg.H4.BackgroundColor = nil
	cfg.H4.Bold = boolPtr(true)
	// Code spans → neutral; cockpit wraps the flow/status lines in
	// backticks to preserve monospace, not to flag "this is code."
	cfg.Code.BackgroundColor = nil
	cfg.Code.Color = nil
	cfg.CodeBlock.Chroma = nil // no syntax highlighting for cockpit blocks
	// Emphasis is fine; strong-emphasis (queue capped) stays bold.
	return cfg
}

func boolPtr(b bool) *bool       { return &b }
func stringPtr(s string) *string { return &s }

// tableHeaderStyle paints the table header row (the line directly
// above the ─┼─ separator) in a distinct accent. Glamour's StyleTable
// only lets us pick the separator glyphs, not differentiate rows —
// so we post-process the rendered output.
var tableHeaderStyle = lipgloss.NewStyle().
	Foreground(lipgloss.AdaptiveColor{Light: "130", Dark: "173"}). // dull orange — rust on light, peach on dark
	Bold(true)

// ansiCSI matches CSI escape sequences (`\x1b[...m` and friends) so we
// can strip glamour's per-cell color reset codes before re-styling the
// whole header line — otherwise our wrap gets cancelled at every
// internal reset.
var ansiCSI = regexp.MustCompile(`\x1b\[[\d;?]*[A-Za-z]`)

func colorizeTableHeader(s string) string {
	lines := strings.Split(s, "\n")
	for i := 1; i < len(lines); i++ {
		t := strings.TrimSpace(lines[i])
		if t == "" {
			continue
		}
		// Separator line: contains ─ and ┼ and nothing else of substance.
		if strings.ContainsRune(t, '─') && strings.ContainsRune(t, '┼') {
			clean := ansiCSI.ReplaceAllString(lines[i-1], "")
			lines[i-1] = tableHeaderStyle.Render(clean)
			break
		}
	}
	return strings.Join(lines, "\n")
}

// pulseGlyph styled in the on-color so the dot reads as "fresh" not noise.
var pulseGlyph = lipgloss.NewStyle().Foreground(onColor).Bold(true).Render(" ·")

// injectPulse finds the first non-empty line in body and appends the
// pulse glyph to it. The first non-empty line is the H1 ("coding
// factory — cockpit"), since glamour leaves a blank first line for
// padding. Works for any view: inbox shows "# inbox — empty", lanes
// shows "# sweep lanes — PRs by station".
func injectPulse(body string) string {
	lines := strings.Split(body, "\n")
	for i, line := range lines {
		if strings.TrimSpace(line) == "" {
			continue
		}
		lines[i] = strings.TrimRight(line, " ") + pulseGlyph
		break
	}
	return strings.Join(lines, "\n")
}

// appendH1Emoji puts the view's emoji to the right of the H1 line so
// every view's title carries its own factory glyph (🏭 cockpit, 📥 inbox,
// 🛣 lanes, 🗑 waste). Skips if the emoji already appears in the line —
// idempotent so it's safe to call before injectPulse.
func appendH1Emoji(body, emoji string) string {
	if emoji == "" {
		return body
	}
	lines := strings.Split(body, "\n")
	for i, line := range lines {
		trim := strings.TrimSpace(line)
		if trim == "" {
			continue
		}
		if strings.Contains(line, emoji) {
			break
		}
		lines[i] = strings.TrimRight(line, " ") + " " + emoji
		break
	}
	return strings.Join(lines, "\n")
}

const (
	dryFlag      = "dry"
	pauseFlag    = "paused"
	refreshEvery = 5 * time.Second
)

// controlDirPath is resolved once at startup. If $HOME can't be found,
// main() bails before constructing the model — the TUI must read from
// the same directory the CLI writes to, or it silently disagrees about
// where the flags live and operator clicks vanish into ./.sweep/.
var controlDirPath string

func flagPath(name string) string { return filepath.Join(controlDirPath, name) }

// flagState returns presence, plus any anomaly that wasn't simple
// absence. Treating permission-denied or IO errors as "off" hides
// disagreement between the TUI and the CLI from the operator — the
// bar would render OFF while the pipeline still thinks the flag is on.
// Anomalies surface in the status line.
func flagState(name string) (on bool, anomaly error) {
	_, err := os.Stat(flagPath(name))
	if err == nil {
		return true, nil
	}
	if errors.Is(err, os.ErrNotExist) {
		return false, nil
	}
	return false, err
}

func setFlag(name string, on bool) error {
	if on {
		// controlDirPath is created at startup, so OpenFile alone is
		// enough here. If something removed the dir mid-run, the open
		// fails and surfaces in the status line.
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
	dimColor    = lipgloss.AdaptiveColor{Light: "240", Dark: "8"}  // hints (legible text)
	borderColor = lipgloss.AdaptiveColor{Light: "250", Dark: "237"} // off-state border (softer than text — frames, not chrome)
	onColor     = lipgloss.AdaptiveColor{Light: "166", Dark: "11"} // on-state border + label (orange on light, yellow on dark)
	keyColor    = lipgloss.AdaptiveColor{Light: "27", Dark: "6"}   // keybinding glyph

	itemBox = lipgloss.NewStyle().
		Padding(0, 2).
		Border(lipgloss.RoundedBorder()).
		BorderForeground(borderColor)
	itemBoxOn = itemBox.Copy().
			BorderForeground(onColor).
			Foreground(onColor).
			Bold(true)
	keyStyle  = lipgloss.NewStyle().Foreground(keyColor).Bold(true)
	hintStyle = lipgloss.NewStyle().Foreground(dimColor)

	// viewBox wraps the snapshot body in the same rounded ASCII frame
	// as the buttons — same border color, same corner glyphs, so the
	// whole TUI reads as one composition rather than bar + raw text.
	viewBox = lipgloss.NewStyle().
		Padding(0, 1).
		Border(lipgloss.RoundedBorder()).
		BorderForeground(borderColor)
)

// --------------- model
//
// flag values are snapshotted into the model on each tick / keypress so
// View() reads from a consistent set even if the filesystem flips
// mid-render. The snapshot is also the place where CLI flips become
// visible: `tickMsg` fires every refreshEvery, re-stats both flags, and
// triggers a re-render only if the values changed (cheap, no flicker).

// Views cycle under one `c` key — hacker ergonomic, single-keystroke
// rotation. Add new views by appending here; the cycle picks them up.
// Each entry names the sweep subcommand args used to render it.
var views = []struct {
	emoji string
	label string
	args  []string
}{
	{"🏭", "cockpit", []string{"cockpit", "--plain"}},
	{"📥", "inbox", []string{"inbox"}},
	{"🛣", "lanes", []string{"lanes"}},
	{"🗑", "wasteboard", []string{"waste"}},
	{"🧪", "hygraph", []string{"hygraph"}},
}

type model struct {
	dryOn        bool
	paused       bool
	status       string    // last message under the bar (action feedback or fetch failure)
	viewIdx      int       // current entry in `views`
	viewBody     string    // last fetched output for the current view
	width        int       // terminal width, fed by tea.WindowSizeMsg; 80 fallback
	pulseExpires time.Time // until this moment, append a ` ·` to the view's H1 line
	// N+1 prefetch buffer — keyed by view index, holds rendered bodies
	// ready to swap in instantly on `c`. Cleared on width change (re-
	// rendered at wrong wrap) and on tick (stale-bound to ~5s).
	prefetched map[int]string
}

const pulseDuration = 400 * time.Millisecond

type tickMsg time.Time
type statusMsg string
type viewMsg string
type pulseMsg struct{}

// prefetchMsg carries a rendered body for a non-current view, dropped
// into model.prefetched so the next `c` keypress lands instantly.
type prefetchMsg struct {
	idx  int
	body string
}

// renderView shells out to `sweep <cmd>` and pipes through glamour.
// Shared by foreground fetch (returns viewMsg) and background
// prefetch (returns prefetchMsg).
func renderView(idx, width int) string {
	args := views[idx].args
	raw, err := exec.Command("sweep", args...).Output()
	if err != nil {
		return fmt.Sprintf("%s error: %v", views[idx].label, err)
	}
	if width < 40 {
		width = 80
	}
	r, err := glamour.NewTermRenderer(
		glamour.WithStyles(sweepGlamourStyle()),
		glamour.WithWordWrap(width),
	)
	if err != nil {
		return string(raw)
	}
	styled, err := r.Render(string(raw))
	if err != nil {
		return string(raw)
	}
	return colorizeTableHeader(styled)
}

func fetchView(idx, width int) tea.Cmd {
	return func() tea.Msg { return viewMsg(renderView(idx, width)) }
}

// prefetchView renders the next view in the cycle into the model's
// prefetch buffer so the next `c` lands instantly. Game-dev style
// double-buffer: render N+1 while operator looks at N.
func prefetchView(idx, width int) tea.Cmd {
	return func() tea.Msg {
		return prefetchMsg{idx: idx, body: renderView(idx, width)}
	}
}

func nextIdx(idx int) int { return (idx + 1) % len(views) }

// restartWorker shells out `sweep down && sweep up` async so the TUI
// stays interactive during the ~2s lifecycle bounce. The final
// statusMsg lands on the bar so the operator sees the outcome.
func restartWorker() tea.Cmd {
	return func() tea.Msg {
		if out, err := exec.Command("sweep", "down").CombinedOutput(); err != nil {
			return statusMsg(fmt.Sprintf("restart: down failed: %v (%s)",
				err, strings.TrimSpace(string(out))))
		}
		if out, err := exec.Command("sweep", "up").CombinedOutput(); err != nil {
			return statusMsg(fmt.Sprintf("restart: up failed: %v (%s)",
				err, strings.TrimSpace(string(out))))
		}
		return statusMsg("restarted")
	}
}

func tick() tea.Cmd {
	return tea.Tick(refreshEvery, func(t time.Time) tea.Msg { return tickMsg(t) })
}

// snapshot reads both flag files and returns a model plus an anomaly
// string (empty when both reads were clean ENOENT-or-present). Callers
// merge the anomaly into m.status; toggle success clears it.
func snapshot() (model, string) {
	m := model{}
	var anomalies []string
	if on, err := flagState(dryFlag); err != nil {
		anomalies = append(anomalies, fmt.Sprintf("dry: %v", err))
	} else {
		m.dryOn = on
	}
	if on, err := flagState(pauseFlag); err != nil {
		anomalies = append(anomalies, fmt.Sprintf("paused: %v", err))
	} else {
		m.paused = on
	}
	return m, strings.Join(anomalies, "; ")
}

func (m model) Init() tea.Cmd { return tea.Batch(tick(), fetchView(m.viewIdx, m.width)) }

// refresh re-snapshots and folds an optional status override in. If the
// snapshot itself flagged an anomaly, that wins over the override —
// data-integrity messages are more important than transient feedback.
// Preserves the last cockpit render across refreshes so the screen
// doesn't flash blank between async fetches.
func refresh(prev model, override string) model {
	s, anomaly := snapshot()
	switch {
	case anomaly != "":
		s.status = anomaly
	case override != "":
		s.status = override
	default:
		s.status = prev.status
	}
	s.viewIdx = prev.viewIdx
	s.viewBody = prev.viewBody
	s.width = prev.width
	s.pulseExpires = prev.pulseExpires
	return s
}

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.KeyMsg:
		switch msg.String() {
		case "q", "ctrl+c", "esc":
			return m, tea.Quit
		case "r":
			// Restart the worker so code edits to budget/knobs/activities
			// take effect. `sweep down && sweep up` is the canonical
			// lifecycle pair; we shell out async so the TUI stays live.
			m.status = "restarting…"
			return m, restartWorker()
		case "d":
			if err := setFlag(dryFlag, !m.dryOn); err != nil {
				m.status = fmt.Sprintf("dry toggle failed: %v", err)
				return m, nil
			}
			// refresh re-reads disk rather than trusting `!m.dryOn` —
			// if the write succeeded but disk disagrees (mid-flight CLI
			// flip, fs weirdness), the bar shows what's actually there.
			return refresh(m, ""), nil
		case "p":
			if err := setFlag(pauseFlag, !m.paused); err != nil {
				m.status = fmt.Sprintf("pause toggle failed: %v", err)
				return m, nil
			}
			return refresh(m, ""), nil
		case "c":
			// Cycle to next view. If the prefetcher already rendered
			// it (the common case after the first ~150ms in any
			// session), swap instantly — perceived latency is one
			// paint. Otherwise fall back to sync fetch.
			next := nextIdx(m.viewIdx)
			m.viewIdx = next
			if body, ok := m.prefetched[next]; ok {
				m.viewBody = body
				delete(m.prefetched, next)
				m.pulseExpires = time.Now().Add(pulseDuration)
				// Queue the next-next so the buffer stays one ahead.
				return m, tea.Batch(
					prefetchView(nextIdx(next), m.width),
					tea.Tick(pulseDuration, func(time.Time) tea.Msg { return pulseMsg{} }),
				)
			}
			m.viewBody = ""
			return m, fetchView(m.viewIdx, m.width)
		}

	case tea.WindowSizeMsg:
		// Width changed — any prefetched bodies were rendered at the
		// wrong wrap. Clear the buffer and re-fetch the current view.
		m.width = msg.Width
		m.prefetched = nil
		return m, fetchView(m.viewIdx, m.width)

	case tickMsg:
		// 5s tick: re-fetch current view AND invalidate the prefetch
		// buffer so the operator never cycles to a 5s-stale render.
		// The next prefetch fires automatically when the new viewMsg
		// lands.
		next := refresh(m, m.status)
		next.prefetched = nil
		return next, tea.Batch(tick(), fetchView(m.viewIdx, m.width))

	case viewMsg:
		m.viewBody = string(msg)
		m.pulseExpires = time.Now().Add(pulseDuration)
		// Got the current view; immediately queue N+1 in the
		// background. Buffer is keyed by viewIdx so out-of-order
		// landings still place correctly.
		return m, tea.Batch(
			prefetchView(nextIdx(m.viewIdx), m.width),
			tea.Tick(pulseDuration, func(time.Time) tea.Msg { return pulseMsg{} }),
		)

	case prefetchMsg:
		// Stash the rendered body unless the operator already cycled
		// past it (idx no longer the immediate next). Stale-after-
		// cycle prefetch results are silently dropped.
		if msg.idx == nextIdx(m.viewIdx) {
			if m.prefetched == nil {
				m.prefetched = map[int]string{}
			}
			m.prefetched[msg.idx] = msg.body
		}
		return m, nil

	case pulseMsg:
		return m, nil // pulse window already encoded in pulseExpires; this just forces a redraw

	case statusMsg:
		// Re-snapshot on subprocess return: 5s of `sweep cockpit` is
		// enough time for the operator (or anything else) to flip a
		// flag, and the bar should reflect that immediately.
		return refresh(m, string(msg)), nil
	}
	return m, nil
}

func (m model) View() string {
	dryLabel := fmt.Sprintf("%s %s", keyStyle.Render("d"), modeBadge(m.dryOn, "🌵 DRY", "💧 LIVE"))
	pauseLabel := fmt.Sprintf("%s %s", keyStyle.Render("p"), modeBadge(m.paused, "🚦 PAUSED", "🟢 RUNNING"))
	v := views[m.viewIdx]
	viewLabel := fmt.Sprintf("%s 🔄 cycle", keyStyle.Render("c"))

	bar := lipgloss.JoinHorizontal(
		lipgloss.Top,
		boxFor(m.dryOn, dryLabel),
		"  ",
		boxFor(m.paused, pauseLabel),
		"  ",
		itemBox.Render(viewLabel),
	)

	hint := hintStyle.Render(fmt.Sprintf("%s cycle view   %s restart   %s quit   flags live at %s",
		keyStyle.Render("c"), keyStyle.Render("r"), keyStyle.Render("q"), controlDirPath))

	out := bar + "\n" + hint
	if m.status != "" {
		out += "\n" + hintStyle.Render(m.status)
	}
	if m.viewBody != "" {
		// Trim the trailing newline glamour appends so the bottom border
		// hugs the content instead of leaving an empty interior row.
		body := strings.TrimRight(m.viewBody, "\n")
		// Append the view's emoji to the right of the H1 so every
		// title carries its factory glyph. Done before the pulse so
		// the pulse dot lands at the far right when active.
		body = appendH1Emoji(body, v.emoji)
		// Pulse: while the refresh window is open, append a subtle dot
		// to the first non-empty line so the operator's eye registers
		// that the snapshot just updated.
		if time.Now().Before(m.pulseExpires) {
			body = injectPulse(body)
		}
		out += "\n\n" + viewBox.Render(body)
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

// modeBadge picks the on/off label literally so each branch ships its
// own emoji + word. Both literals are visually inspected for the same
// cell width — emoji renderers disagree about width, so changing one
// side without checking the other can shift the box edge on flip.
func modeBadge(on bool, onLabel, offLabel string) string {
	if on {
		return onLabel
	}
	return offLabel
}

// renderOnce prints View() once and exits. Used by the test harness to
// exercise lipgloss styling under varying TERM / NO_COLOR without
// needing a PTY for the Bubble Tea event loop. Reads flag state at
// call time so the rendered output matches what an operator would see.
func renderOnce() {
	m, anomaly := snapshot()
	m.status = anomaly
	fmt.Print(m.View())
}

// resolveControlDir resolves $HOME and ensures the control dir is
// usable. Doing the MkdirAll + IsDir check once at startup means a
// filesystem problem (regular file at ~/.sweep/control, parent dir
// read-only) surfaces with a clear exit message instead of the first
// toggle failing silently.
func resolveControlDir() error {
	home, err := os.UserHomeDir()
	if err != nil {
		return fmt.Errorf("could not resolve home directory: %w", err)
	}
	controlDirPath = filepath.Join(home, ".sweep", "control")
	if err := os.MkdirAll(controlDirPath, 0o755); err != nil {
		return fmt.Errorf("could not create %s: %w", controlDirPath, err)
	}
	info, err := os.Stat(controlDirPath)
	if err != nil {
		return fmt.Errorf("could not stat %s: %w", controlDirPath, err)
	}
	if !info.IsDir() {
		return fmt.Errorf("%s exists but is not a directory", controlDirPath)
	}
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
	if len(os.Args) > 1 && os.Args[1] == "--lanes" {
		lm, err := loadLanes()
		if err != nil {
			fmt.Fprintln(os.Stderr, "sweep-tui --lanes:", err)
			os.Exit(1)
		}
		p := tea.NewProgram(lm, tea.WithAltScreen())
		if _, err := p.Run(); err != nil {
			fmt.Fprintln(os.Stderr, "sweep-tui --lanes:", err)
			os.Exit(1)
		}
		return
	}
	// Self-heal: if the previous TUI hard-crashed (SIGKILL, panic in
	// goroutine, power loss) it left orphans. Reap them before taking
	// the lock so the new session starts from a clean slate.
	reapPreviousOwned()
	// One TUI per machine. Two operator surfaces flipping the same
	// flags is the path to "wait, why is dry off now?" surprises.
	if err := acquireSessionLock(); err != nil {
		fmt.Fprintln(os.Stderr, "sweep-tui:", err)
		os.Exit(1)
	}
	defer releaseSessionLock()
	// Bring the pipe up via the canonical `sweep up`. The TUI tears
	// down only what it started: services that were already running
	// (e.g. someone ran `sweep up` from SSH first) stay running on
	// TUI quit. Run `sweep down` to tear those down explicitly.
	lifecycleAnomalies, owned := bringUp()
	persistOwned(owned)
	defer tearDownOwned(owned)
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
	m, anomaly := snapshot()
	m.status = anomaly
	if len(lifecycleAnomalies) > 0 {
		joined := strings.Join(lifecycleAnomalies, "; ")
		if m.status == "" {
			m.status = joined
		} else {
			m.status = m.status + "; " + joined
		}
	}
	// Alt-screen (DEC mode ?1049): clears the screen on entry, restores
	// prior scrollback on quit. Earlier the bar was a one-line inline
	// thing where keeping scrollback mattered; now it also embeds a
	// full cockpit/inbox/lanes view, so an alt-screen "dedicated room"
	// reads better and quitting still hands the terminal back clean.
	p := tea.NewProgram(m, tea.WithAltScreen())
	if _, err := p.Run(); err != nil {
		fmt.Fprintln(os.Stderr, "sweep-tui:", err)
		os.Exit(1)
	}
}
