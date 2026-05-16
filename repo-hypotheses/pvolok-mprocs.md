# pvolok/mprocs Triage Graph

## Scan (2026-05-09)

Solo-maintainer Rust TUI tool (2.5k stars, 65+ open issues). Strategy: smallest first contribution, earn trust.

### DENYLIST (attempted, killed)

| # | Reason | Verdict |
|---|--------|---------|
| 212 | autostart color indicator | Gemini gate: config != runtime state. Manually-started autostart:false proc crashing via signal would show gray not red. |

### Issues evaluated (by simplicity rank)

| # | Title | Complexity | Outcome |
|---|-------|-----------|----------|
| 162 | JSON schema missing scrollback | External repo (SchemaStore) | SKIP: out of scope |
| 185 | Debian/Ubuntu install instructions incorrect | Documentation fix | **MERGED** PR #216 |
| 182 | Documentation for command modal | Documentation fix | **QUEUED** (docs/182-document-command-modal) |
| n/a | Homebrew TOC inconsistency | Documentation fix | **QUEUED** (docs/fix-homebrew-toc-inconsistency) |
| n/a | Procfile typo (Profile→Procfile) | Documentation fix | **QUEUED** (docs/fix-procfile-typo) |
| 215 | Arrow keys fire on keydown+keyup | Windows input handling bug | SKIP: too complex |
| 152 | Disable mouse in global config | Feature request (needs implementation) | SKIP: not trivial |

### Queued for drip

| Branch | Issue | SHA | Status |
|--------|-------|-----|--------|
| fix/185-remove-broken-mpr-install | #185 | aabcd71 | merged |
| docs/182-document-command-modal | #182 | 0be4794 | queued |
| docs/fix-homebrew-toc-inconsistency | (none) | 6d62b2d | queued |
| docs/fix-procfile-typo | (none) | fe48bf3 | queued |

---

## Issue #185: Remove unmaintained MPR installation instructions

**Status**: Queued for drip  
**Branch**: fix/185-remove-broken-mpr-install  
**Commit**: aabcd71

### Problem

README references makedeb/MPR package manager which is unmaintained. URL (mpr.makedeb.org) returns 502.

### Fix

Removed MPR (Debian/Ubuntu) section from README and table of contents. Pure subtraction — users can use binary download method instead.

### Maintainer acknowledgment

Maintainer (pvolok) acknowledged in issue comments: "I should make a script for installing mprocs on any Linux distribution" but hasn't done it yet. This fix removes broken content without waiting for a replacement.

### Files Modified

- `README.md`: Removed MPR section (lines 107-113) and TOC entry (line 39)

---

## Issue #182: Documentation for command modal

**Status**: Queued for drip  
**Branch**: docs/182-document-command-modal  
**Commit**: 0be4794

### Problem

The command modal (opened with `p` key) is mentioned in the keymap but has no documentation explaining what it does or how to use it. Users who don't discover it by accident miss out on a helpful feature for discovering commands and their key bindings.

### Fix

Added a new "How to use the command menu" section in README.md, following the same format as the existing "How to copy text" section. Explains:

- What it is (searchable modal showing all commands with key bindings)
- How to open it (press `p`)
- How to filter (type to search)
- How to navigate (arrow keys or C-n/C-p)
- How to execute (Enter) or cancel (Esc)

### Files Modified

- `README.md`: Added 10-line documentation section after "Copy mode" keymap

---

## Homebrew TOC inconsistency

**Status**: Queued for drip  
**Branch**: docs/fix-homebrew-toc-inconsistency  
**Commit**: 6d62b2d

### Problem

Table of contents links to "homebrew (Macos)" but the actual section header is "homebrew (Macos, Linux)". This creates a mismatch and could confuse Linux users looking for installation instructions.

### Fix

Updated TOC to match section header: changed anchor from `#homebrew-macos` to `#homebrew-macos-linux`.

### Files Modified

- `README.md`: Single-line TOC fix

---

## Procfile typo

**Status**: Queued for drip  
**Branch**: docs/fix-procfile-typo  
**Commit**: fe48bf3

### Problem

Documentation comment says "# default: Profile" but the actual default filename is "Procfile" (verified in `src/mprocs/mprocs.rs` line with `.default_missing_value("Procfile")`).

### Fix

Changed "Profile" to "Procfile" in the example code comment.

### Files Modified

- `README.md`: Single-character typo fix

---

## Issue #212: autostart:false procs shouldn't be red (KILLED)

**Status**: Gate fail (Gemini)  
**Branch**: fix/212-autostart-color  
**Commit**: e2f3a2d

### Problem

Processes with `autostart: false` show as red (error state) in the TUI when they haven't been started yet. This gives the false impression that something is wrong when the process is simply not running by design.

### Root Cause

In `src/mprocs/ui_procs.rs` lines 95-111, the status color logic treats all processes without an exit code (`None`) as errors (red):

- UP → GREEN
- DOWN with exit code 0 → BLUE  
- DOWN with non-zero exit code → RED
- DOWN with no exit code → RED (BUG)

The fourth case includes both:
1. Processes that crashed before setting an exit code (legitimately red)
2. Processes with autostart:false that were never started (should be neutral)

### Fix

Added a check in the `None` exit code branch: if `proc.cfg.autostart` is false, use gray (`Color::BRIGHT_BLACK`) instead of red.

```rust
None => {
  // Process never started - check if autostart is false
  if !proc.cfg.autostart {
    (Cow::from(" DOWN "), attrs.clone().fg(Color::BRIGHT_BLACK))
  } else {
    (Cow::from(" DOWN "), attrs.clone().fg(Color::BRIGHT_RED))
  }
}
```

### Testing

- `cargo build --lib`: compiles successfully
- `cargo test`: 25/26 tests pass (1 pre-existing failure unrelated to this change)

### Files Modified

- `src/mprocs/ui_procs.rs`: Added autostart check in status color logic
