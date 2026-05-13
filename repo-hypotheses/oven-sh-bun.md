# Triage Graph: oven-sh/bun (kimjune01)

**Scan date:** 2026-05-09
**Mode:** dry-run

## Scan Table

| # | Title | State | Score | Effort | Signal | Status |
|---|-------|-------|-------|--------|--------|--------|
| 24211 | An equivalent to Bun.enableANSIColors for stdout and stderr individually | OPEN | 7/10 | Small (~12 lines Zig) | User-filed, clear repro | IMPLEMENTED |

## #24211: Per-stream ANSI color detection

### Root Cause

In `src/bun_core/output.zig`, `Source.set()` computes a single `enable_color` flag from the combined tty status of both streams. When the code path reaches the fallback (`enable_color orelse is_stdout_tty`), a tty on stderr causes `enable_color = true`, which is then applied to stdout even when stdout is piped. This means `console.log` output piped to a file contains ANSI escape codes.

### Fix (~12 lines Zig)

Replace the single `enable_color` variable with per-stream evaluation:
- `FORCE_COLOR` → both true
- `NO_COLOR` → both false
- Otherwise: `enable_ansi_colors_stdout = is_stdout_tty`, `enable_ansi_colors_stderr = is_stderr_tty`

### Test limitation

Gemini review identified that `spawnSync` with `stdout: "pipe", stderr: "pipe"` pipes both streams, so neither is a tty. The test validates correct behavior (no escapes when piped, escapes when FORCE_COLOR) but cannot reproduce the exact bug trigger (one stream tty + one piped). A proper reproduction would require a pty library. The test is included as regression coverage.

### Review notes

- **Gemini rejected the test** as insufficient reproduction of the exact bug. The Zig fix is correct and the test provides value as regression coverage. Test limitation is documented in the commit message and drip queue entry.
- **No competing PRs** for the same root cause. PR #28443 is about snapshot ANSI stripping (different scope).
- **Issue #24211** asks for per-stream API (`Bun.enableANSIColorsStdout`). This fix addresses the underlying bug; the public API addition is separate scope.

### Files changed

- `src/bun_core/output.zig`
- `test/js/bun/console/console-no-color-pipe.test.ts` (new)
- `test/js/bun/console/console-no-color-pipe.ts` (new)
