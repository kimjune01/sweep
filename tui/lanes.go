// Lanes — 2D nav overlay for `sweep lanes`. Column-major: Tab walks
// columns, 1-9 selects the row in the focused column, Enter shells out
// to `sweep pr <ref>`. 0 advances to the next page when the column
// truncated. q quits back to the bar.
//
// Data comes from `sweep lanes --json`. The markdown view stays
// unchanged; this is overlay chrome.

package main

import (
	"encoding/json"
	"fmt"
	"os/exec"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

type laneItem struct {
	Repo     string `json:"repo"`
	Pr       any    `json:"pr"`
	InFlight bool   `json:"in_flight"`
}

type lane struct {
	Label string     `json:"label"`
	Items []laneItem `json:"items"`
}

const pageSize = 9 // 1-9 row selectors; 0 advances page

type lanesModel struct {
	lanes   []lane
	col     int   // focused column
	page    []int // page offset per column, in pageSize chunks
	status  string
}

func loadLanes() (lanesModel, error) {
	out, err := exec.Command("sweep", "lanes", "--json").Output()
	if err != nil {
		return lanesModel{}, fmt.Errorf("sweep lanes --json: %w", err)
	}
	var ls []lane
	if err := json.Unmarshal(out, &ls); err != nil {
		return lanesModel{}, fmt.Errorf("parse lanes json: %w", err)
	}
	return lanesModel{lanes: ls, page: make([]int, len(ls))}, nil
}

func (m lanesModel) Init() tea.Cmd { return nil }

func (m lanesModel) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	key, ok := msg.(tea.KeyMsg)
	if !ok {
		return m, nil
	}
	switch key.String() {
	case "q", "ctrl+c", "esc":
		return m, tea.Quit
	case "tab", "l", "right":
		if len(m.lanes) > 0 {
			m.col = (m.col + 1) % len(m.lanes)
		}
		m.status = ""
		return m, nil
	case "shift+tab", "h", "left":
		if len(m.lanes) > 0 {
			m.col = (m.col - 1 + len(m.lanes)) % len(m.lanes)
		}
		m.status = ""
		return m, nil
	case "0":
		// Pagination: advance focused column if there's more.
		if m.col < len(m.lanes) {
			items := m.lanes[m.col].Items
			if (m.page[m.col]+1)*pageSize < len(items) {
				m.page[m.col]++
			} else {
				m.page[m.col] = 0 // wrap
			}
		}
		return m, nil
	case "1", "2", "3", "4", "5", "6", "7", "8", "9":
		idx := int(key.String()[0] - '1')
		return m.open(idx)
	case "enter":
		return m.open(0)
	}
	return m, nil
}

func (m lanesModel) open(rowInPage int) (tea.Model, tea.Cmd) {
	if m.col >= len(m.lanes) {
		return m, nil
	}
	items := m.lanes[m.col].Items
	abs := m.page[m.col]*pageSize + rowInPage
	if abs >= len(items) {
		return m, nil // no-op for rows beyond the column
	}
	item := items[abs]
	ref := fmt.Sprintf("%s#%v", item.Repo, item.Pr)
	return m, tea.ExecProcess(exec.Command("sweep", "pr", ref), func(err error) tea.Msg {
		if err != nil {
			return statusMsg(fmt.Sprintf("sweep pr %s: %v", ref, err))
		}
		return statusMsg("")
	})
}

var (
	// Lane headers wear the same rounded ASCII frame as the bar
	// buttons — focused column borrows the on-color so it pops, the
	// rest use the soft borderColor so they recede.
	laneHeader = lipgloss.NewStyle().
		Padding(0, 1).
		Border(lipgloss.RoundedBorder()).
		BorderForeground(borderColor)
	laneHeaderFocused = laneHeader.Copy().
				BorderForeground(onColor).
				Foreground(onColor).
				Bold(true)
	laneRow           = lipgloss.NewStyle().Padding(0, 1)
	laneRowFocused    = laneRow.Copy().Foreground(onColor)
	laneGutter        = lipgloss.NewStyle().Foreground(keyColor).Bold(true)
)

func (m lanesModel) View() string {
	if len(m.lanes) == 0 {
		return "no lanes\n\nq quit\n"
	}
	cols := make([]string, len(m.lanes))
	for i, ln := range m.lanes {
		header := fmt.Sprintf("%s (%d)", ln.Label, len(ln.Items))
		if i == m.col {
			cols[i] = laneHeaderFocused.Render("▸ " + header)
		} else {
			cols[i] = laneHeader.Render("  " + header)
		}
		start := m.page[i] * pageSize
		end := start + pageSize
		if end > len(ln.Items) {
			end = len(ln.Items)
		}
		rowStyle := laneRow
		if i == m.col {
			rowStyle = laneRowFocused
		}
		for r := start; r < end; r++ {
			item := ln.Items[r]
			gutter := ""
			if i == m.col {
				gutter = laneGutter.Render(fmt.Sprintf("%d ", r-start+1))
			} else {
				gutter = "  "
			}
			prefix := ""
			if item.InFlight {
				prefix = "✈️ "
			}
			line := fmt.Sprintf("%s%s%s#%v", gutter, prefix, item.Repo, item.Pr)
			cols[i] += "\n" + rowStyle.Render(line)
		}
		if end < len(ln.Items) {
			more := fmt.Sprintf("  … +%d more", len(ln.Items)-end)
			if i == m.col {
				more = laneGutter.Render("0 ") + fmt.Sprintf("… +%d more", len(ln.Items)-end)
			}
			cols[i] += "\n" + rowStyle.Render(more)
		}
	}
	body := lipgloss.JoinHorizontal(lipgloss.Top, cols...)
	hint := hintStyle.Render("tab/shift-tab cols   1-9 open   0 next page   enter open top   q quit")
	out := body + "\n\n" + hint
	if m.status != "" {
		out += "\n" + hintStyle.Render(m.status)
	}
	return out + "\n"
}
