// Backend lifecycle. The TUI tears down what it started, not what it
// found. On launch it shells out to `sweep up --json` and remembers
// which services were freshly spawned (state == "started"); on quit it
// SIGKILLs exactly those PIDs and leaves anything that was already
// running alone.
//
// Ergonomics: `sweep up` from shell → backend persists across TUI
// quit / SSH disconnect. `sweep-tui` alone → backend lives and dies
// with the TUI. Neither owns the other.

package main

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
)

type serviceState struct {
	State string `json:"state"`
	Pid   int    `json:"pid"`
}

// bringUp shells out to `sweep up --json` and returns:
//   - status lines for the bar
//   - PIDs of services the TUI freshly started (to kill on quit)
func bringUp() (lines []string, owned map[string]int) {
	owned = map[string]int{}
	cmd := exec.Command("sweep", "up", "--json")
	out, err := cmd.Output()
	if err != nil {
		return []string{fmt.Sprintf("sweep up: %v", err)}, owned
	}
	var result map[string]serviceState
	if err := json.Unmarshal(out, &result); err != nil {
		return []string{fmt.Sprintf("sweep up: bad json (%v)", err)}, owned
	}
	for label, s := range result {
		switch s.State {
		case "started":
			owned[label] = s.Pid
			lines = append(lines, fmt.Sprintf("%s started (pid %d)", label, s.Pid))
		case "already_running":
			lines = append(lines, fmt.Sprintf("%s attached (pid %d)", label, s.Pid))
		case "skipped":
			lines = append(lines, fmt.Sprintf("%s skipped", label))
		}
	}
	return lines, owned
}

// tearDownOwned SIGKILLs only the services we started. Anything the
// user brought up via `sweep up` from shell stays running.
func tearDownOwned(owned map[string]int) {
	for _, pid := range owned {
		syscall.Kill(pid, syscall.SIGKILL)
	}
	os.Remove(filepath.Join(controlDirPath, "tui_owned.json"))
}

// persistOwned writes the owned-PID map so that if this TUI crashes
// hard (SIGKILL, panic in goroutine, power loss) the next launch can
// find the orphans and SIGKILL them. Self-healing without a daemon.
func persistOwned(owned map[string]int) {
	if len(owned) == 0 {
		return
	}
	data, err := json.Marshal(owned)
	if err != nil {
		return
	}
	os.WriteFile(filepath.Join(controlDirPath, "tui_owned.json"), data, 0o644)
}

// reapPreviousOwned runs before the session lock check. If tui.pid is
// stale (process dead) and tui_owned.json exists, kill those PIDs.
// Clears both files. No-op when the previous TUI exited cleanly
// (tearDownOwned removed the file) or when there was no previous TUI.
func reapPreviousOwned() {
	tuiPidPath := filepath.Join(controlDirPath, "tui.pid")
	ownedPath := filepath.Join(controlDirPath, "tui_owned.json")
	if data, err := os.ReadFile(tuiPidPath); err == nil {
		if pid, err := strconv.Atoi(strings.TrimSpace(string(data))); err == nil {
			if err := syscall.Kill(pid, 0); err == nil {
				return // previous TUI is alive; lock check will reject us
			}
		}
	}
	if data, err := os.ReadFile(ownedPath); err == nil {
		var owned map[string]int
		if json.Unmarshal(data, &owned) == nil {
			for _, pid := range owned {
				syscall.Kill(pid, syscall.SIGKILL)
			}
		}
		os.Remove(ownedPath)
	}
}

// acquireSessionLock enforces one sweep-tui per machine. Writes our
// PID to ~/.sweep/control/tui.pid; if the file exists and the PID is
// alive, refuse to start. Stale lock (process gone) → take it over.
func acquireSessionLock() error {
	path := filepath.Join(controlDirPath, "tui.pid")
	if data, err := os.ReadFile(path); err == nil {
		if pid, err := strconv.Atoi(strings.TrimSpace(string(data))); err == nil {
			if err := syscall.Kill(pid, 0); err == nil {
				return fmt.Errorf("another sweep-tui is running (pid %d). quit it or `rm %s` if stale", pid, path)
			}
		}
	}
	return os.WriteFile(path, []byte(strconv.Itoa(os.Getpid())+"\n"), 0o644)
}

func releaseSessionLock() {
	path := filepath.Join(controlDirPath, "tui.pid")
	if data, err := os.ReadFile(path); err == nil {
		if pid, err := strconv.Atoi(strings.TrimSpace(string(data))); err == nil && pid == os.Getpid() {
			os.Remove(path)
		}
	}
}
