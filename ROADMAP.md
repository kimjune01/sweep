# Roadmap

The branch `temporal-pipeline` is 87 commits ahead of `master`. Below is what's shipped, what's next, and what's intentionally deferred.

## Shipped

### Substrate

- `sweep/gh_io.py` — SQLite-cached wrapper around `gh` CLI. Sync API; shlex-aware query splitting; per-endpoint hit/miss counters. All sweep code routes through it.
- `sweep/llm_io.py` — Anthropic SDK wrapper with attestation logging. `APIError` caught, recorded to `observe.event`, re-raised (no cache poisoning).
- `sweep/attestations.py` — SQLite + Merkle chain. `record_call` serialized with `BEGIN IMMEDIATE` so concurrent writers can't fork the chain.
- `sweep/io_safe.py::atomic_write_text` — used everywhere stateful state lands: cursors, caches, retro pagers.
- `sweep/fuses.py` — event-pinned attestation invalidation (head SHA, base SHA, review ID).

### Observability

- `sweep/observe.py` — append-only `events.jsonl` + UPSERT `counters.db` + cursor (`events.cursor`).
- Instrumented call sites: gh_io (hit/miss), qa (volley + verdict), prospect (cursor + repos/issues), pr_state (bucket), seen (dedup), llm_io (errors).
- `sweep observe counters / events / cursor / advance` — read-side ops.

### Retro pager (the backward pass)

- `sweep/retro_state.py` — SOAP one-pager directory at `~/.sweep/retros/` capped at 2 files. Round-blocks append into active empty-P chains; new file when prior has a prescription. `pipeline_halted` event fires when the cap-reaching write lands.
- `sweep/cli/retro.py` — `list / status / show / discard / record` (skill-facing interface).
- `scripts/draft-retro.py` — Haiku-driven end-to-end exerciser.
- Forward pass actors (`prospect_one_pass`, `qa_one_entry`, `route_classified`) check `is_halted()` at takt boundaries.

### Cockpit

- `sweep cockpit` — single status line + compressed flow + per-station table + human inbox. The gemba view.
- `sweep lanes` — per-station swim lanes with PR detail.
- Markdown-piped: same source bytes render in terminal, glow, Claude Code, GitHub comments.
- Inbox surfaces: 💬 respond, ⬆️ force-push, 🤝 manual-merge, 🖋 sign-off, 🌱 retro actionable.

### Tests

- `scripts/e2e-haiku.py` — substrate test against live Anthropic API.
- `scripts/e2e-fixture.py` — full qa pipeline against live GitHub + Haiku.
- Both green.

### Operator controls + TUI

- `sweep/control_state.py` — flag primitives at `~/.sweep/control/{dry,paused}`. Presence-only, atomic writes.
- `sweep dry on/off/status` and `sweep pause on/off/status` — CLI toggles. Same files the TUI writes.
- Dry mode skips external mutations at three sites: `deliver_to_inbox`, `route_classified`, and `prospect_one_pass`'s deposit step — each writes to a `.dry.jsonl` sibling and emits a `dry_skip` event. The drip skill's `gh pr create` honors the same flag.
- Soft-pause: `prospect_one_pass`, `qa_one_entry`, and `route_classified` no-op at takt entry (counters `paused_skip:*`). In-flight work completes; clears manually.
- `sweep cockpit` status line surfaces 🚦 PAUSED and 🌵 DRY when active.
- `tui/` — Bubble Tea action bar built to `bin/sweep-tui`. One-line horizontal bar with three boxes (dry, pause, floor); polls `~/.sweep/control/` every 5s so external CLI flips show up live; `d`/`p` toggle, `r` manual refresh, `f` shells out to `sweep cockpit`, `q` quit. File-backed flags persist across launches and the CLI.
- Chewy TUI audit pass (May 2026). Walked `tui/main.go` against the [Chewy TUI](https://june.kim/chewy-tui) palette and pitfalls. Now load-bearing: adaptive light/dark colors via `lipgloss.AdaptiveColor` (legible on Solarized Light *and* xterm dark), defensive trailing-space padding on the 🌵/🚦 emoji so the right edge holds on macOS Terminal.app, and anchor comments at every `tea.NewProgram` option and color declaration mapping the choice back to a named heuristic (alt-screen vs inline, mouse mode ?1006 not ?1000, bracketed paste ?2004, Synchronized Output ?2026 emitted by Bubble Tea's default renderer, NO_COLOR via termenv, Ctrl-C → SIGINT, isatty fallback on `sweep-tui | cat`, `len(s)` vs runewidth). Piped invocation exits 1 with a stderr message; verified.

### Hardening

Seven rounds of adversarial bug hunt (`bug-hunt.md` is the current report). 30 bugs fixed across rounds 1–7: shlex label quoting, cursor atomicity, SQLite timeouts, chain race serialization, llm error cache poisoning, ack inbox writer gap, route_classified msg_id stability, and the long tail of cousin bugs each fix surfaces.

## Up next

Ordered by readiness, not strict priority.

### 1. clig.dev ergonomics pass — `BOOTSTRAP-CLIG.md`

Self-contained prompt for a fresh session. Ten sections: help-text examples, exit codes (0/1/2), stdout/stderr split, `--json` on read commands, confirmation prompts on destructive ops, `NO_COLOR`, tab completion, `--version`, `-q / --quiet`, misuse-vs-traceback messages. CLI-only; substrate untouched.

### 2. Retro skill markdown — `~/.claude/skills/retro/skill.md`

The `/retro` skill currently has the old prose. Replace with: read events via `sweep observe events`, read counters via `sweep observe counters`, draft four SOAP sections, call `sweep retro record --subjective ... --plan ...`. `scripts/draft-retro.py` is the working prototype to lift from.

### 3. Inbox writer side — close round 7's high-severity gap

Pre-existing architectural debt. `_acks.jsonl` and `_started.jsonl` have no writers; every message stays in `queued` forever. The cockpit's `in_flight` and `done` columns are structurally permanent zeros.

Proposed shape: actors emit `observe.event("actor_started" / "actor_completed", msg_id=...)`. `inbox_state.py` derives buckets by replaying events instead of reading separate jsonl files. Three files collapse to one; the cursor we already have demarcates retro's reading window.

### 4. PrStateWorkflow migration

Round 7 M1. The Temporal workflow still calls the coupled `deliver_to_inbox`; the decoupled `deposit_classified` + `route_classified` pair is only used by the CLI. Migrate the workflow so the documented benefit (routing rule changes don't require re-classification) actually applies under cron.

### 5. Adversarial cascade in qa

`qa_volley_hist` is always `:1` because the codex → gemini → codex cascade isn't implemented yet. Wire the round-2/round-3 retry loop in `qa_actor.py` so the histogram becomes non-degenerate and reviewer disagreement actually drives more rounds.

### 6. Force-push producer

Renderer is ready (⬆️ in the inbox); no producer yet. Candidates:
- `pr_state` detects "rebase" / "force-push" / "squash" in review comments.
- `drip` escalates to respondable when its automated push hits non-fast-forward.
- Branch-protection / `CONTRIBUTING.md` parsing for repos that require linear history.

Pick one, prototype, see if it earns its keep.

### 7. Onboarding

Friction we keep hitting and a newcomer would hit harder. README's quick-start covers commands; this covers the gap between "ran the commands" and "knows what's happening."

- **Hardlink-vs-symlink convention.** Quick-start mixes both: state-dir uses `ln -s`, skill files and HYPOTHESIS_GRAPH use `ln` (hard). Hardlinks silently detach on `git checkout` of a different version (working tree gets a new inode; the `~/.sweep` side keeps pointing at the old). Pick a rule per file class and document the failure mode. Likely: symlinks for skill files (point at versioned source), hardlinks only for files actively edited on both sides.
- **`~/.sweep/` directory map.** What lives where, what's ephemeral cache (`cache/`), what's append-only log (`events.jsonl`), what's pager state (`retros/`), what's tamper-evident (`attestations/`). One section in README or a `STATE.md` next to it. Currently a newcomer has to grep.
- **TUI ↔ CLI relationship.** `sweep-tui` shells out to `sweep` for every action; if `sweep` isn't on PATH the TUI dies with an opaque "executable file not found." Make this explicit in README's TUI section (the install step now fixes the symptom but not the explanation).
- **First-cycle walkthrough.** README §5 is a command catalog. Newcomer wants narrative: clone → install → `prospect` produces what → triage filters how → drip queues → push → retro folds → repeat. One annotated example PR through the whole loop, with a screenshot of `sweep cockpit` at each stage.

## Later

- **Cold storage for events.** The cursor was built for this — once retro proves it captures everything it needs across a few cycles, the lines before the cursor become safe to archive (gzip + S3 / wherever). Until then, events.jsonl grows append-only and that's fine.
- **Counter histograms for retro.** `qa_volley_hist:1`, `qa_volley_hist:2`, … etc. already work; need a CLI/skill that reads them and surfaces distribution shape (`sweep observe hist qa_volley`).
- **TUI kanban item selection.** `sweep-tui` currently exposes the two pipeline-wide flags as a horizontal action bar. Per-item actions (select a PR row in the kanban, ack / open in browser / clear from inbox) would let the TUI cover the swim-lane operator surface too. Out of scope until the bar version earns its keep.
- **Wish front door for remote control.** Wrap `sweep-tui` in [Charm Wish](https://github.com/charmbracelet/wish) so `ssh sweep@factory` lands directly in the TUI with no shell in between, no local binary install, no login session. Today's path (`ssh factory; sweep-tui`) already works; Wish collapses it into one hop. Make sense when sweep runs unattended on a remote box and the operator wants a single-command control plane. ~50 lines of Go, one `sweep-tui --serve :2222` flag. Defer until there's a real remote deployment that wants it.

## Flagged, not doing (yet)

- 24h user-identity TTL across a mid-day `gh auth login` switch. Acceptable for single-operator use; reconsider for shared/CI deployments.
- Whitespace-only diff misidentified as empty in qa — exits non-retryable with a misleading message. Edge case; the surrounding guard catches the real failure.
- `runtest.py` untracked-then-future-tracked collision in `e2e-fixture.py`. No current bug; flag if the fixture evolves.
- Orphaned `search_issues` cache rows in `gh.db` after the prospect migration. They expire on TTL; cosmetic.
- `manual-merge` intent: 99.999% won't fire. Renderer carries the glyph anyway.

## Out of scope

- Renaming things that already work. The board → kanban rename and punch → floor rename are done; no more.
- A second cockpit view. `sweep cockpit` + `sweep lanes` are the surfaces. Anything more goes in those two.
- Reimplementing observability primitives in another store (Prometheus, Honeycomb, etc.). The events.jsonl + counters.db pair is intentionally local and greppable.

## How to read this file

Each section's bullets point at source files or markdown specs (`BOOTSTRAP-CLIG.md`, `bug-hunt.md`). The roadmap names what to do next; the bootstraps name how. Anything not in either is either shipped or intentionally not happening yet.
