# Bootstrap — TUI with operator controls

Paste this into a fresh Claude Code session at `~/Documents/sweep` on branch `temporal-pipeline`. Self-contained.

---

## Context

`sweep floor` is the markdown-piped cockpit. It renders styled in a TTY (via `glow`), pipes raw for scripting, refreshes via `--watch`. Read-only — no operator controls beyond what the actors expose via their own subcommands (`sweep retro discard`, `sweep qa actor clear`, etc.).

What's missing: a live operator surface for two pipeline-wide controls.

- **Dry mode** — actors run the full forward pass but skip *external mutations*. No `gh pr create`, no `git push`, no `gh issue close`, no review comments. Everything observable still fires (events, counters, attestations, retros), so the operator can see what *would have* happened. The line rehearses without touching the world.
- **Soft-pause** — forward-pass actors stop dequeuing new work at takt entry, but in-flight work completes normally. Distinct from the retro cap halt (`📋 RETRO`, which is automatic backpressure); soft-pause is operator-initiated and clears manually. Drip queue freezes; qa cascade in flight finishes.

These need to be toggleable without context-switching to a separate terminal. The natural surface is a TUI that wraps `sweep floor` with two keybindings.

## Scope

Two halves: substrate (Python, no new deps) + TUI (Go, Bubble Tea).

### A. Substrate

1. **`sweep/control_state.py`** — flag primitives.

   ```python
   CONTROL = Path.home() / ".sweep" / "control"

   def is_dry() -> bool: ...      # ~/.sweep/control/dry
   def is_paused() -> bool: ...   # ~/.sweep/control/paused
   def set_dry(v: bool) -> None: ...
   def set_paused(v: bool) -> None: ...
   ```

   Atomic writes via `io_safe.atomic_write_text`. File presence = on. Empty file is fine; truthy content not required. Same pattern as `retro_state` — the file IS the state.

2. **CLI** — `sweep dry on/off/status` and `sweep pause on/off/status`. Live with `sweep floor` and `sweep kanban` at the top level (not nested under a parent). Mirror `sweep retro` shape.

3. **Actor wiring**.
   - `prospect_one_pass`: check `is_paused()`; if true, no-op return (same shape as the retro halt path; emits `halted_skip:prospect` analogue → `paused_skip:prospect`).
   - `qa_one_entry`: check `is_paused()`; if true, raise `ApplicationError(non_retryable=False)` (retryable because clearing the pause flips the gate).
   - `route_classified`: check `is_paused()`; if true, return `{halted: False, paused: True, read: 0, routed: {}, skipped_acked: 0}`.
   - `deliver_to_inbox` (used in drip path): when `is_dry()`, write to a `~/.sweep/inbox/<actor>.dry.jsonl` sibling instead of the real inbox. Or emit `observe.event("dry_skip", ...)` and skip — pick the option that better matches "rehearsal trace I can read later."
   - Push site in drip / `gh pr create` site: when `is_dry()`, emit `observe.event("dry_skip", site="gh_pr_create", ...)` and return as if it succeeded.

   Wire it at the point where mutation hits the wire, not at takt entry. Tests still run, attestations still write, observability still records — only the *external write* is skipped.

4. **Surface in `sweep floor`'s status line**.

   ```
   `cpu 0% · mem 47% · 0 agents · 🚦 PAUSED · 🌵 DRY`
   ```

   Cells render only when active. 🚦 (traffic light, U+1F6A6) for pause; 🌵 (cactus, U+1F335 — "rehearsing in the desert, nothing real on the line") for dry. Both can coexist.

### B. TUI

`tui/` directory at repo root with a small Go module using Bubble Tea + Lip Gloss + Bubbles.

1. **Build**: `cd tui && go build -o ../bin/sweep-tui` (or `go install ./tui` once the module is set up).
2. **Behavior**: launch with `sweep-tui`. The TUI renders the output of `sweep floor --plain` (subprocess every 5s by default — same takt as `--watch`). Keybindings:
   - `d` — toggle dry mode (writes `~/.sweep/control/dry`).
   - `p` — toggle pause (writes `~/.sweep/control/paused`).
   - `r` — refresh now (skip the 5s timer).
   - `q` / `Ctrl-C` — quit.
3. **Render via Glamour** (Charm's markdown renderer; Glow uses it internally). Feed the markdown straight through; no custom styling needed.
4. **Status footer**: a single line under the rendered floor showing the keybindings and current dry/pause state:
   ```
   d dry [🌵 ON]   p pause [—]   r refresh   q quit
   ```
5. **Resilience**: if `sweep floor --plain` fails (worker down, gh auth expired), render the stderr in red and keep the previous good frame on screen.

The TUI is the salesperson; the Python substrate is the factory. Neither ships alone: the factory without a storefront is a personal tool nobody discovers; the storefront without a factory is a demo. They are one product across two languages, bridged by flag files at `~/.sweep/control/` — TUI writes them, Python actors read them, same files the CLI subcommands write so all three surfaces are interchangeable.

## Acceptance

- `sweep dry on; sweep floor` shows 🌵 DRY in the status line.
- `sweep dry on; uv run sweep qa full ... --worktree /tmp/fixture` runs cascade, writes attestation rows, emits events, and skips the would-be `git push` / `gh pr create` (verified via `sweep observe events --kind dry_skip`).
- `sweep pause on; uv run sweep prospect run` returns immediately with a `paused_skip:prospect` counter incremented; in-flight qa from before the pause completes.
- `sweep-tui` launches, renders the same content as `sweep floor`, responds to `d`/`p`/`r`/`q`. Hold both flags on, quit, re-launch — the flags persist (file-backed).
- `scripts/e2e-haiku.py` and `scripts/e2e-fixture.py` still pass.

## Style

- Commit messages: lowercase subject with area prefix (`control:`, `tui:`, `dry:`). One commit per logical chunk. Match `git log --oneline -10`.
- Don't bundle dry-mode wiring across activities into one commit — `qa: skip git push under dry`, `drip: skip gh pr create under dry`, etc.
- **Both halves ship together.** Substrate without the TUI is a tool that nobody can see; TUI without the substrate is a demo with no engine. Land them in the same cycle. If the substrate is ready and the TUI isn't, keep going — don't merge the half.
- No new Python deps. Go side gets Bubble Tea + Lip Gloss + Bubbles + Glamour — match versions used in `glow`'s go.mod if helpful.
- Don't add a "force kill in-flight" mode. Soft-pause is *soft* by design; in-flight always completes.

## Out of scope

- Token-free dry mode (skip LLM calls). Separate flag, separate ticket.
- Resume signal that aborts the current takt's wait. The actor's next takt is fine.
- Cross-machine flag sync. Files are local; multi-machine deployments add their own coordination.
- Replacing `sweep floor` with the TUI. The CLI is still the primary surface; the TUI is the operator's live control room.

## Done = green

When the substrate + TUI both land:
- `sweep dry on/off/status` and `sweep pause on/off/status` work, with status flags rendering in `sweep floor`.
- Actor wiring verifiable via the `dry_skip` and `paused_skip:*` events / counters.
- `sweep-tui` is a launchable binary that lets you flip both flags without leaving the screen.
- `git log --oneline temporal-pipeline ^master | grep -i -E 'control|dry|pause|tui'` shows a clean per-step commit cluster.
- ROADMAP.md gains a "Shipped" entry for "Operator controls + TUI" and removes the corresponding "Bubble Tea overlay" line under "Later."
