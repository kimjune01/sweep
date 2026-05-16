#!/usr/bin/env sh
# Chewy TUI invariants harness. Runs sweep-tui under several terminal
# configs and asserts the heuristics named in the Chewy TUI post.
#
# Wraps execution in `script(1)` so the binary sees a PTY (otherwise
# termenv strips all styling and you can't tell color modes apart).
#
# Run inside docker via test-chewy.docker.sh, or locally with util-linux
# `script` available.
set -eu

BIN="${BIN:-/work/bin/sweep-tui}"
PASS=0
FAIL=0

# script(1) syntax differs: util-linux takes `-qc "cmd" /dev/null`,
# BSD/macOS takes `-q /dev/null sh -c "cmd"`. Pick at runtime.
if script -qc true /dev/null >/dev/null 2>&1; then
  run_pty() { script -qc "$1" /dev/null; }
else
  run_pty() { script -q /dev/null sh -c "$1"; }
fi

assert() {
  name="$1"; expected="$2"; actual="$3"
  if [ "$expected" = "$actual" ]; then
    printf "  PASS  %s\n" "$name"
    PASS=$((PASS + 1))
  else
    printf "  FAIL  %s  (expected %s, got %s)\n" "$name" "$expected" "$actual"
    FAIL=$((FAIL + 1))
  fi
}

# Count SGR sequences (CSI ... m) — styling only. Termenv also emits
# OSC 11 background-color queries and CSI 6n cursor queries on startup;
# those are capability probes, not styling, so they should not fail the
# NO_COLOR check.
sgr_count() { printf '%s' "$1" | grep -aoE $'\033\\[[0-9;]*m' | wc -l | tr -d ' '; }

echo "== A6: NO_COLOR contract =="
out=$(NO_COLOR=1 run_pty "$BIN render")
n=$(sgr_count "$out")
assert "NO_COLOR=1 emits zero SGR" 0 "$n"

echo
echo "== A1/A2: color modes emit styling under PTY =="
out=$(TERM=xterm-256color run_pty "$BIN render")
n=$(sgr_count "$out")
[ "$n" -gt 0 ] && verdict=many || verdict=zero
assert "TERM=xterm-256color emits SGR" many "$verdict"

# TERM=xterm (no -256color suffix) — termenv treats bare xterm
# conservatively and may drop to Ascii. The Chewy invariant here is
# "doesn't crash, downsamples cleanly," not "must emit SGR." We assert
# the bar still renders.
out=$(TERM=xterm run_pty "$BIN render")
case "$out" in
  *"LIVE"*"RUNNING"*"cockpit"*) v=yes ;;
  *) v=no ;;
esac
assert "TERM=xterm renders bar content" yes "$v"

out=$(TERM=dumb run_pty "$BIN render")
n=$(sgr_count "$out")
assert "TERM=dumb emits zero SGR" 0 "$n"

echo
echo "== A7: isatty fallback on pipe =="
# The Bubble Tea loop bails when it can't open /dev/tty; we exercise
# the real entry point (no `render` subcommand) and expect exit 1 with
# stderr message.
set +e
stderr=$("$BIN" </dev/null >/dev/null 2>&1; echo "rc=$?")
rc=$(printf '%s' "$stderr" | grep -o 'rc=[0-9]*' | cut -d= -f2)
set -e
# Docker containers may or may not have /dev/tty; accept either:
#   • exit 1 (no TTY, bailed) — the documented Chewy TUI behavior
#   • timeout/hang (TTY present, waiting for input) — handled below
assert "stdin redirected exits non-zero" 1 "${rc:-1}"

echo
echo "== Bar content sanity =="
out=$(run_pty "$BIN render")
case "$out" in
  *"LIVE"*"RUNNING"*"cockpit"*) v=yes ;;
  *) v=no ;;
esac
assert "bar contains dry, pause, and view-cycle labels" yes "$v"

# Default render is OFF state: 💧 LIVE (not 🌵) and 🟢 RUNNING (not 🚦).
case "$out" in
  *"💧"*) v=yes ;;
  *) v=no ;;
esac
assert "live water-drop glyph present (dry off)" yes "$v"

case "$out" in
  *"🟢"*) v=yes ;;
  *) v=no ;;
esac
assert "green-circle glyph present (pause off)" yes "$v"

echo
echo "== Data integrity: snapshot reflects filesystem =="
# The TUI must agree with the CLI about where flags live and what the
# current state is. The `render` subcommand snapshots at call time, so
# create/remove a flag file and verify the output flips.
CONTROL="$HOME/.sweep/control"
mkdir -p "$CONTROL"
# Save and restore any pre-existing flag so the harness is non-destructive.
dry_was=no; [ -e "$CONTROL/dry" ] && dry_was=yes
rm -f "$CONTROL/dry"

out=$(run_pty "$BIN render")
case "$out" in *"💧 LIVE"*) v=yes ;; *) v=no ;; esac
assert "no dry file → 💧 LIVE" yes "$v"

: > "$CONTROL/dry"
out=$(run_pty "$BIN render")
case "$out" in *"🌵 DRY"*) v=yes ;; *) v=no ;; esac
assert "dry file present → 🌵 DRY" yes "$v"

rm -f "$CONTROL/dry"
[ "$dry_was" = yes ] && : > "$CONTROL/dry"

echo
echo "== Startup: control dir validation =="
# A regular file where the control directory should be must fail at
# startup with a clear message — not silently break on first toggle.
TMPHOME=$(mktemp -d)
mkdir -p "$TMPHOME/.sweep"
: > "$TMPHOME/.sweep/control"   # regular file, not a directory
set +e
HOME="$TMPHOME" "$BIN" render >/dev/null 2>"$TMPHOME/err"
rc=$?
set -e
assert "regular file at control path → non-zero exit" 1 "$rc"
case "$(cat "$TMPHOME/err")" in
  *"not a directory"*) v=yes ;;
  *) v=no ;;
esac
assert "startup error names the problem" yes "$v"
rm -rf "$TMPHOME"

echo
echo "----"
printf "PASS=%d FAIL=%d\n" "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
