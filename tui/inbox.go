// Inbox — operator overlay for the human inbox. Lists unacked cards;
// digit selects, `d` shells `sweep inbox done <ref>` (ack + re-remit),
// enter opens detail via `sweep pr`. `q` quits back to the bar.
//
// Data comes from `sweep inbox actor human --json`. The markdown view
// stays unchanged; this is overlay chrome.

package main

import (
	"encoding/json"
	"fmt"
	"os/exec"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

type inboxCard struct {
	MsgId  string `json:"msg_id"`
	Repo   string `json:"repo"`
	Pr     any    `json:"pr"`
	Intent string `json:"intent"`
	Reason string `json:"reason"`
	Cmd    string `json:"cmd"`
}

const inboxPageSize = 9

type inboxModel struct {
	cards  []inboxCard
	page   int
	status string
}

func loadInbox() (inboxModel, error) {
	out, err := exec.Command("sweep", "inbox", "actor", "human", "--json").Output()
	if err != nil {
		return inboxModel{}, fmt.Errorf("sweep inbox actor human --json: %w", err)
	}
	var cs []inboxCard
	if err := json.Unmarshal(out, &cs); err != nil {
		return inboxModel{}, fmt.Errorf("parse inbox json: %w", err)
	}
	return inboxModel{cards: cs}, nil
}

func (m inboxModel) Init() tea.Cmd { return nil }

func (m inboxModel) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	key, ok := msg.(tea.KeyMsg)
	if !ok {
		return m, nil
	}
	switch key.String() {
	case "q", "ctrl+c", "esc":
		return m, tea.Quit
	case "0":
		if len(m.cards) > 0 && (m.page+1)*inboxPageSize < len(m.cards) {
			m.page++
		} else {
			m.page = 0
		}
		m.status = ""
		return m, nil
	case "r":
		// Refresh from disk.
		fresh, err := loadInbox()
		if err != nil {
			m.status = fmt.Sprintf("refresh failed: %v", err)
			return m, nil
		}
		fresh.status = "refreshed"
		return fresh, nil
	case "1", "2", "3", "4", "5", "6", "7", "8", "9":
		idx := int(key.String()[0]-'1') + m.page*inboxPageSize
		return m.open(idx)
	case "k", "K":
		// One key, remit ALL unacked cards: ack each + kick remit per
		// (repo, pr). Per-card done was an earlier shape; operator
		// preference is bulk-action because after a batch of pushes
		// the right move is "re-observe everything," not card-by-card.
		return m.doneAll()
	case "enter":
		return m.open(m.page * inboxPageSize)
	}
	return m, nil
}

func (m inboxModel) open(idx int) (tea.Model, tea.Cmd) {
	if idx >= len(m.cards) {
		m.status = fmt.Sprintf("no card at index %d", idx+1)
		return m, nil
	}
	c := m.cards[idx]
	pr := fmt.Sprintf("%v", c.Pr)
	if c.Repo == "" || pr == "" || pr == "<nil>" {
		m.status = fmt.Sprintf("card %d has no repo/pr", idx+1)
		return m, nil
	}
	ref := fmt.Sprintf("%s#%s", c.Repo, pr)
	cmd := exec.Command("sweep", "pr", ref)
	out, err := cmd.CombinedOutput()
	if err != nil {
		m.status = fmt.Sprintf("sweep pr %s failed: %v", ref, err)
		return m, nil
	}
	m.status = string(out)
	return m, nil
}

func (m inboxModel) doneAll() (tea.Model, tea.Cmd) {
	if len(m.cards) == 0 {
		m.status = "inbox already empty"
		return m, nil
	}
	// Dedup (repo, pr) — multiple cards can refer to the same PR; one
	// remit kick per pair is enough since remit re-classifies from
	// current PR state regardless of which card kicked it.
	seen := map[string]bool{}
	var refs []string
	for _, c := range m.cards {
		pr := fmt.Sprintf("%v", c.Pr)
		if c.Repo == "" || pr == "" || pr == "<nil>" {
			continue
		}
		ref := fmt.Sprintf("%s#%s", c.Repo, pr)
		if seen[ref] {
			continue
		}
		seen[ref] = true
		refs = append(refs, ref)
	}
	if len(refs) == 0 {
		m.status = "no actionable (repo, pr) cards in inbox"
		return m, nil
	}
	var oks, fails int
	var report string
	for _, ref := range refs {
		out, err := exec.Command("sweep", "inbox", "done", ref).CombinedOutput()
		if err != nil {
			fails++
			report += fmt.Sprintf("  ✗ %s: %v\n", ref, err)
			continue
		}
		oks++
		report += fmt.Sprintf("  ✓ %s\n%s", ref, indent(string(out), "    "))
	}
	fresh, _ := loadInbox()
	fresh.status = fmt.Sprintf("done %d ok, %d failed\n%s", oks, fails, report)
	return fresh, nil
}

func indent(s, prefix string) string {
	if s == "" {
		return ""
	}
	out := ""
	for _, line := range splitLines(s) {
		out += prefix + line + "\n"
	}
	return out
}

func splitLines(s string) []string {
	var out []string
	start := 0
	for i := 0; i < len(s); i++ {
		if s[i] == '\n' {
			out = append(out, s[start:i])
			start = i + 1
		}
	}
	if start < len(s) {
		out = append(out, s[start:])
	}
	return out
}

func (m inboxModel) View() string {
	header := lipgloss.NewStyle().Bold(true).Render("inbox (human)")
	if len(m.cards) == 0 {
		return header + "\n\nempty\n\nq quit\n"
	}
	rowStyle := lipgloss.NewStyle()
	keyStyle := lipgloss.NewStyle().Foreground(lipgloss.Color("11"))
	cmdStyle := lipgloss.NewStyle().Foreground(lipgloss.Color("8"))
	start := m.page * inboxPageSize
	end := start + inboxPageSize
	if end > len(m.cards) {
		end = len(m.cards)
	}
	body := ""
	for i, c := range m.cards[start:end] {
		pr := fmt.Sprintf("%v", c.Pr)
		head := fmt.Sprintf("%s %s#%s  %s",
			keyStyle.Render(fmt.Sprintf("[%d]", i+1)),
			c.Repo, pr, c.Intent,
		)
		body += rowStyle.Render(head) + "\n"
		if c.Reason != "" {
			body += "    " + c.Reason + "\n"
		}
		if c.Cmd != "" {
			body += "    " + cmdStyle.Render("$ "+c.Cmd) + "\n"
		}
	}
	pageInfo := fmt.Sprintf("  page %d/%d  (%d cards)",
		m.page+1, (len(m.cards)+inboxPageSize-1)/inboxPageSize, len(m.cards))
	hint := lipgloss.NewStyle().Foreground(lipgloss.Color("8")).Render(
		"1-9 open detail   k remit ALL   0 next page   r refresh   q quit")
	out := header + pageInfo + "\n\n" + body + "\n" + hint
	if m.status != "" {
		out += "\n\n" + m.status
	}
	return out
}
