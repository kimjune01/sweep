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

- `sweep floor` — single status line + compressed flow + per-station table + human inbox. The gemba view.
- `sweep kanban` — per-station swim lanes with PR detail.
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
- `sweep floor` status line surfaces 🚦 PAUSED and 🌵 DRY when active.
- `tui/` — Bubble Tea + Glamour TUI built to `bin/sweep-tui`. Wraps `sweep floor --plain`, refreshes every 5s, `d`/`p`/`r`/`q` keybinds. File-backed so flags persist across launches.

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

## Later

- **Cold storage for events.** The cursor was built for this — once retro proves it captures everything it needs across a few cycles, the lines before the cursor become safe to archive (gzip + S3 / wherever). Until then, events.jsonl grows append-only and that's fine.
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
- A second cockpit view. `sweep floor` + `sweep kanban` are the surfaces. Anything more goes in those two.
- Reimplementing observability primitives in another store (Prometheus, Honeycomb, etc.). The events.jsonl + counters.db pair is intentionally local and greppable.

## How to read this file

Each section's bullets point at source files or markdown specs (`BOOTSTRAP-CLIG.md`, `bug-hunt.md`). The roadmap names what to do next; the bootstraps name how. Anything not in either is either shipped or intentionally not happening yet.
