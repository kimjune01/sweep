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

- Production is the test. Real PRs to real repos perturb the substrate
  harder than any isolated harness — andons, retries, merge politics,
  CI quirks are the signal. The earlier Haiku harness was disposed of
  once the live pipeline reliably surfaced its own failures.

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

**Dual-mandate filter** (2026-05-17 grooming): every item ordered by whether it moves both axes — 📈 merge rate + 🔬 falsifiable hypothesis. Ergonomics-only (🛠) demoted to "Later" or "Ergonomics (single-operator deferral)" below. Refactor-only items (code purity, no value delta) demoted to "Defer until witness."

### 📈🔬 Dual-axis (do these first)

#### 1. Pre-investigate: discussion as prework

📈 cuts re-discovery; PR body references prior maintainer thinking. 🔬 falsifier: pre-investigate cards merge at same rate as bare-investigate cards over N≥20 pairs → kill the pre-pass. See HYPOTHESIS_GRAPH H24 + the "From bulk-attest practice round" section below.

#### 2. Maintainer-ROI ranking (H24 implementation)

📈 sorts the budget toward higher-prior bets. 🔬 H24 has explicit falsifiers (ROI score correlates with components but not merge rate → refit; ROI score correlates with neither → kill the feature). Slots between sift and triage as a sort key. Witness: bulk-attest practice round's wide variance in outcome wasn't predicted by language/size, but did correlate with rough ROI proxies.

#### 3. Adversarial cascade in qa

📈 catches bugs round-1 misses, lifts merge-on-real-fix rate. 🔬 falsifier: round-2/round-3 produce zero additional verdicts vs round-1 over N≥50 cards → cascade is theater, cut it. `qa_volley_hist` is the instrumentation already in place. Wire the round-2/round-3 retry loop in `qa_actor.py`.

#### 4. /compose skill

📈 PR body quality is a known merge predictor (H17 hypothesis-graph footer; same axis applies to compose-written sections). 🔬 falsifier: PRs whose compose template-provenance differs from skill-provenance merge at the same rate → template is enough, kill the skill. Wiring is in place (qa → attest → compose → submit + idempotent splice); the skill replaces the template.

#### 5. Auto-infer test_env / test_cmd / test_setup_cmd

📈 every new repo currently needs 3 manual `sweep retro set` invocations before its first attest; that friction throttles the substrate's reach. 🔬 falsifier: heuristic-inferred params produce attest verdicts at the same rate as operator-set ones → ship the heuristic; otherwise the LLM-inference fallback. Detect from lockfiles (pnpm-lock.yaml, Cargo.lock, go.sum, Gemfile.lock) + workflow YAMLs.

#### 6. Codex/gemini attestations under `attestations/<slug>/` umbrella

📈 multi-family review footer in PR body extends the H17 hypothesis ("hypothesis-graph link in PR body raises merge rate") with a second receipt class. 🔬 measurable lift over PRs with attestation footer only. Today qa publishes the test triple; codex/gemini verdicts stay substrate-private. Symmetric work — publish `codex-attestation.json` + `gemini-attestation.json` (verdict + sha256, not full transcript; avoids bot-shaped-communication critique).

#### 7. Force-push producer

📈 PRs that need rebase / force-push block merge until the operator notices; surfacing them in the inbox shortens the human latency. 🔬 falsifier: surfaced force-push intents that the operator clears at the same rate as ambient noticing → channel was already adequate. Renderer is ready (⬆️); candidates: pr_state comment scan, drip non-fast-forward escalation, CONTRIBUTING.md parse.

#### 8. Pokayoke migration

📈 indirect — collapses scattered intake checks into one contract, so new wrong-shape classes only require one new function + entry in per-actor list. 🔬 measurable: drop in `andon_unexpected` events (the rejection-as-third-outcome trichotomy lands properly). Module shipped 2026-05-17; callers (attest, SkillActor, qa, compose) still have ad-hoc inline checks. Sequence: attest → SkillActor universal → qa → compose.

### Defer until witness (no current pain)

- **Inbox writer side** (was #3). Cockpit's in_flight/done columns are zeros; that's cosmetic, doesn't change a merge. Pre-existing architectural debt with no measurable impact on shipped PRs.
- **PrStateWorkflow migration** (was #4). Decoupled deposit_classified + route_classified pair already works via CLI; the workflow-side migration is code purity. Defer until the documented benefit (routing rule changes without re-classification) is actually needed.
- **respond/post external-state tracking.** Defensive; observed failure rate ~0.
- **Branch-on-remote sanity check generalization.** investigate_cycle handles its case; generalization is defensive. Defer until witness ghost-branch case repeats outside investigate.

### Ergonomics (single-operator deferral)

These improve operator quality-of-life without moving the merge-rate or hypothesis-test axes. Single operator currently; they earn their keep when a second operator joins.

- **clig.dev ergonomics pass** (was #1). CLI polish: exit codes, --json, confirmations, NO_COLOR, completion, --version, --quiet. BOOTSTRAP-CLIG.md self-contained.
- **Retro skill markdown** (was #2). Replaces old prose with `sweep observe events`-driven SOAP drafting. Operator-facing.
- **Onboarding** (was #7). Hardlink/symlink convention; ~/.sweep/ directory map; TUI/CLI relationship; first-cycle walkthrough. README §5 is currently a command catalog, not a narrative.
- **Documentation: operator escape hatches.** When operator bypasses andon manually. Onboarding-adjacent.

## Later

- **Cold storage for events.** The cursor was built for this — once retro proves it captures everything it needs across a few cycles, the lines before the cursor become safe to archive (gzip + S3 / wherever). Until then, events.jsonl grows append-only and that's fine.
- **Counter histograms for retro.** `qa_volley_hist:1`, `qa_volley_hist:2`, … etc. already work; need a CLI/skill that reads them and surfaces distribution shape (`sweep observe hist qa_volley`).
- **TUI kanban item selection.** `sweep-tui` currently exposes the two pipeline-wide flags as a horizontal action bar. Per-item actions (select a PR row in the kanban, ack / open in browser / clear from inbox) would let the TUI cover the swim-lane operator surface too. Out of scope until the bar version earns its keep.
- **Wish front door for remote control.** Wrap `sweep-tui` in [Charm Wish](https://github.com/charmbracelet/wish) so `ssh sweep@factory` lands directly in the TUI with no shell in between, no local binary install, no login session. Today's path (`ssh factory; sweep-tui`) already works; Wish collapses it into one hop. Make sense when sweep runs unattended on a remote box and the operator wants a single-command control plane. ~50 lines of Go, one `sweep-tui --serve :2222` flag. Defer until there's a real remote deployment that wants it.

### Shipped during 2026-05-17 grooming pass

- `sweep evict flush --repo X` — walks every actor inbox jsonl and drops cards for the evicted repo. Paired with the activity-entry short-circuit on SkillActor.
- `sweep retro remediation-prompt` — scans events + andon markers for fix-class shapes (no_tests_in_pr, stale-andon-marker), writes bootstrap prompts to `~/.sweep/remediation-prompts/`. Next pattern: `test_setup_cmd` inference from lockfile presence.
- `sweep cache rebuild-image` + `sweep-tester:latest` — fat docker image (Rust+Go+Python+Node+C++ toolchain) as the default `test_env`, replacing per-language image overrides.
- `test_attestation` upgrade — applies test-only diff from fix branch onto master before the master-side gate, so PRs that ADD a test get gated on "does the new test fail on master" rather than the misleading "test suite passes on master" trivial outcome.
- `no_tests_in_pr` verdict — distinct routing path (non-halting; sinks the PR with structured reason). Distinguishes "PR adds no test" from "test exists but passes on master." Pairs with the remediation-prompt write-tests bootstrap.
- `sweep qa backfill-bulk` — bulk-enqueues open authored PRs into qa.jsonl with sink-pair / eviction filters and auto-sinks the approved ones.

### Defer until witness (continued)

- **Branch-on-remote sanity check generalization.** investigate_cycle now ls-remotes the fix branch before kicking qa (catches the [[O1]] ghost-branch case). Similar pattern would help other actors that depend on remote state being a particular shape — submit's `_final_checks` could ls-remote the PR's base ref before declaring it mergeable. Generalization deferred until the witness pattern repeats outside investigate.

## Flagged, not doing (yet)

- 24h user-identity TTL across a mid-day `gh auth login` switch. Acceptable for single-operator use; reconsider for shared/CI deployments.
- Whitespace-only diff misidentified as empty in qa — exits non-retryable with a misleading message. Edge case; the surrounding guard catches the real failure.
- Orphaned `search_issues` cache rows in `gh.db` after the prospect migration. They expire on TTL; cosmetic.
- `manual-merge` intent: 99.999% won't fire. Renderer carries the glyph anyway.

## Out of scope

- Renaming things that already work. The board → kanban rename and punch → floor rename are done; no more.
- A second cockpit view. `sweep cockpit` + `sweep lanes` are the surfaces. Anything more goes in those two.
- Reimplementing observability primitives in another store (Prometheus, Honeycomb, etc.). The events.jsonl + counters.db pair is intentionally local and greppable.

## How to read this file

Each section's bullets point at source files or markdown specs (`BOOTSTRAP-CLIG.md`, `bug-hunt.md`). The roadmap names what to do next; the bootstraps name how. Anything not in either is either shipped or intentionally not happening yet.
