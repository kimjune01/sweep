# Sweep

Two tools, same repo.

**For contributors:** Contribute to open source at scale. A Temporal-supervised pipeline finds maintainer-acknowledged bugs, writes failing tests, implements fixes, runs adversarial code review, and queues PRs at a pace that builds standing instead of getting banned. One PR per org at a time, every gate has a hashed receipt, andon halts the line when a postcondition fails.

**For maintainers:** [Protect your repo against AI slop.](#pr-quality-gate) Same checks the pipeline enforces on itself, packaged as a GitHub Action. Advisory, not blocking.

## What it does

Scans GitHub for repos with acknowledged bugs, picks the actionable ones, writes failing tests and minimal fixes, runs codex + gemini as adversarial reviewers, captures each reviewer's raw response as a tamper-evident receipt, and ships through a paced drip queue. The supervisor (a Temporal workflow) restarts crashed work, halts on contract violations, and exposes a deep-linked Web UI for one-hop investigation when something goes wrong.

Status: see [ROADMAP.md](ROADMAP.md) for what's shipped, what's next, and what's deferred.

## Views

Two operator views — both emit GitHub-flavored markdown, both render styled in [glow](https://github.com/charmbracelet/glow) / Claude Code / GitHub comments, both pipe cleanly to grep / clipboard / file.

### `sweep floor` — the factory-floor cockpit

One screen: status line, compressed pipeline flow, per-station table, human inbox under the table.

> `cpu 0% · mem 46% · 0 agents · 🌱 retro`
>
> `Triage ~ Investigate ~ ⌊8⌋ QA ~ ⌊1⌋ Drip ~ ⌊19⌋ In Review ~ Respondable`  _| `sweep kanban`_
>
> | station       | queued | in-flight | rate  | var | trend (10m × 12, % of cap) | oldest | status                |
> | ------------- | -----: | --------: | ----: | :-: | -------------------------- | ------ | --------------------- |
> | → triaged     |      0 |         0 | 0.0/h |  ·  |                            |   —    | idle                  |
> | → investigate |      0 |         0 | 0.0/h |  ·  |                            |   —    | idle                  |
> | → qa          |      8 |         0 | 0.0/h |  ·  |                            |  10h   | **queue capped** (8/3) |
> | → drip        |      1 |         0 | 0.0/h |  ·  |                            |  10h   | queued                |
> | → respondable |      1 |         0 | 0.5/h |  ●  |  ▁                         |   0s   | queued                |
>
> - 🌱 [retro 2026-05-15-1319](file:///Users/you/.sweep/retros/2026-05-15-1319.md)
> - 💬 [mgree/ffs#146](https://github.com/mgree/ffs/pull/146) — maintainer asked: opt-in?
> - ⬆️ [sharkdp/bat#3741](https://github.com/sharkdp/bat/pull/3741) — rebase onto main

Read top-to-bottom: status (is the line green?), flow (where's the pressure?), table (per-station numbers), inbox (what *you* owe — every other station belongs to an LLM actor). Each row tells you more than the one above; scan as far as you need.

- `⌊N⌋` — inbox depth (square-corner brackets read as open buckets, distinct from `( )` for WIP).
- `~` — flow separator between stations.
- `🌱` in the status line — at least one retro pager has a non-empty P. `📋 HALTED` when the cap-of-2 fires.
- Inbox glyphs: 💬 respond, ⬆️ force-push, 🤝 manual-merge, 🖋 sign-off, 🌱 retro actionable.

### `sweep kanban` — the swim-lane drill-down

Per-station PR detail. The flow line in `floor` points here when you want names instead of numbers.

> | triaged (0) | investigate (0) | qa (8) | drip (1) | in review (19) | respondable (1) |
> | ----------- | --------------- | ------ | -------- | -------------- | --------------- |
> |             |                 | [kimjune01/bat#2](https://github.com/kimjune01/bat/pull/2) | [mgree/ffs#146](https://github.com/mgree/ffs/pull/146) | [kimjune01/sptlrx#2](https://github.com/kimjune01/sptlrx/pull/2) | [sharkdp/bat#3741](https://github.com/sharkdp/bat/pull/3741) |
> |             |                 | [sharkdp/bat#3741](https://github.com/sharkdp/bat/pull/3741) |  | [kimjune01/sptlrx#1](https://github.com/kimjune01/sptlrx/pull/1) |  |
> |             |                 | _… +6 more_ |  | _… +17 more_ |  |

Columns truncate at `--height` rows with a `_… +N more_` indicator. Useful when you want to grep "what's actually in qa" rather than "how full is qa."

### When to use which

| Question | View |
|----------|------|
| "Is anything on fire?" | `floor` |
| "What do I owe right now?" | `floor` (inbox at the bottom) |
| "Which PR is in qa?" | `kanban` |
| "Pipe this into Claude / paste into PR comment / write to a file" | either (both are markdown) |
| "Live refresh as the pipeline moves" | `floor -w` (watch mode) |

Both views are read-only. Actions go through actor-specific commands (`sweep retro discard`, `sweep qa clear`, etc.) once the view tells you what to do.

### `sweep-tui` — operator action bar

A thin horizontal bar with two toggles and a link, for flipping pipeline-wide flags without leaving the cockpit. File-backed at `~/.sweep/control/`, so the CLI (`sweep dry on`, `sweep pause on`) and the TUI write the same state.

> `[ d  dry 🌵 OFF ]   [ p  pause 🚦 OFF ]   [ f  floor ↗ ]`
>
> `q quit   flags live at ~/.sweep/control/`

- **Dry** — actors run the full forward pass, tests + attestations + observability still fire, but external mutations (inbox writes, `gh pr create`, `git push`) are skipped. Rehearsal mode. `🌵 DRY` shows up in the `sweep floor` status line.
- **Pause** — forward-pass actors no-op at takt entry; in-flight work completes. Distinct from the retro-cap halt (`📋 RETRO`, automatic backpressure) — pause is operator-initiated. `🚦 PAUSED` shows in `sweep floor`.
- **Floor** — shells out to `sweep floor` so you can drop into the cockpit without quitting the bar.

Build: `cd tui && go build -o ../bin/sweep-tui .`

## Architecture

```
                  ┌────────────────────────────────────────┐
                  │           GitHub (the world)            │
                  └─────────────────┬──────────────────────┘
                                    │ gh / API (via gh_io cache)
                                    ▼
                  ┌─────────────────────────────────────────┐
                  │  pr-state workflow (classifier/dispatcher) │
                  │  buckets: qa | drip | respondable | …    │
                  └────────┬─────────┬──────────┬────────────┘
                           │ signal  │ signal   │ signal
                           ▼         ▼          ▼
                  ┌──────────┐ ┌──────────┐ ┌──────────┐
                  │ QaActor  │ │  inbox   │ │  inbox   │  (Temporal + jsonl)
                  │ WIP=1    │ │ jsonl    │ │ jsonl    │
                  └────┬─────┘ └────┬─────┘ └────┬─────┘
                       │            │            │
                       ▼            ▼            ▼
                  ┌─────────────────────────────────────┐
                  │  Activities — typed, asserted        │
                  │  test_attestation, codex_review,     │
                  │  gemini_review, qa_one_entry, …      │
                  │  Each writes a hashed receipt to     │
                  │  ~/.sweep/attestations/<msg_id>/     │
                  └────────────────┬────────────────────┘
                                    │
                                    ▼
                  ┌─────────────────────────────────────┐
                  │  observe.py — events.jsonl +         │
                  │  counters.db (forward pass)          │
                  │  retro pager — SOAP one-pagers       │
                  │  ~/.sweep/retros/  (backward pass)   │
                  └─────────────────────────────────────┘
```

Two operational modes:

| Mode | When | Substrate |
|------|------|-----------|
| **Terminal** | Manual dev / debug one entry / experiment | Markdown skills in `~/.claude/skills/` invoked from a Claude session. No Temporal. State files written directly to `~/.sweep/`. |
| **Hyper-supervision** | Unattended autonomous runs | Temporal server + Python worker. Workflows orchestrate, activities execute, history is the audit log. No long-running Claude session. |

Skills and Python activities share the same contract — one `msg_id`, one repo, one branch, gates produced with hashed artifacts — so the two modes are interchangeable per entry, not per pipeline.

## Prerequisites

- [Claude Code](https://claude.ai/code) installed
- `gh auth status` passes
- `uv` ([installation](https://docs.astral.sh/uv/getting-started/installation/))
- `temporal` CLI ([installation](https://docs.temporal.io/cli)) — single binary, `temporal server start-dev` is enough
- `ANTHROPIC_API_KEY` set in env (Haiku for tests; Sonnet/Opus for prod)
- `OPENAI_API_KEY` set in env (for codex review)
- A working directory you don't mind cloning repos into (`~/Documents/` by default)

## Quick start

Sweep keeps its state at `~/.sweep/`. The git repo at `~/Documents/sweep/` holds the code. They're separate by design — don't clone this repo into `~/.sweep`.

### 1. Install the code

```bash
git clone https://github.com/kimjune01/sweep ~/Documents/sweep
cd ~/Documents/sweep
uv sync
uv tool install --editable .
```

`uv tool install --editable .` puts `sweep` and `sweep-worker` on user PATH (`~/.local/bin/`), linked to the repo so source edits show up live. Required because the TUI shells out to bare `sweep`.

### 2. Create state directory

```bash
mkdir -p ~/.sweep/{attestations,inbox,retros}
ln -s ~/Documents/sweep/bin ~/.sweep/bin
ln -s ~/Documents/sweep/templates ~/.sweep/templates
```

### 3. Install the skills (terminal mode)

```bash
for skill in drip investigate pr-state prospect qa retro review-schema sweep triage; do
  mkdir -p ~/.claude/skills/"$skill"
  ln ~/Documents/sweep/skills/"$skill".md ~/.claude/skills/"$skill"/skill.md
done
```

### 4. Run the supervisor (hyper-supervision mode)

In one terminal:

```bash
temporal server start-dev
# Web UI now at http://localhost:8233
```

In another terminal:

```bash
cd ~/Documents/sweep
uv run sweep-worker
```

The worker registers `QaActor`, `PrStateWorkflow`, and all activities against task queue `sweep-tq` and waits for signals.

### 5. Drive the pipeline

`sweep` is the CLI (Typer subcommands grouped by concern). Top-level groups:

| Group | What it does |
|-------|--------------|
| `sweep floor` | Factory-floor cockpit — status line + compressed flow + per-station table + human inbox |
| `sweep kanban` | Per-station swim lanes with PR detail |
| `sweep qa` | QA activities (test / codex / gemini / full) + actor signal/status/clear |
| `sweep pr-state` | Classifier + dispatcher (classify / run / scan / route / workflow) |
| `sweep prospect` | Sweep GitHub for actionable issues |
| `sweep inbox` | Per-actor inbox inspector |
| `sweep attest` | Attestation log + gh-cache stats |
| `sweep observe` | Counters + events + cursor for retro |
| `sweep retro` | SOAP one-pager pager — list / status / show / discard / record |
| `sweep dry` | Toggle dry mode (rehearse without external mutations) — on / off / status |
| `sweep pause` | Toggle soft-pause (no new dequeues; in-flight completes) — on / off / status |
| `sweep models` | Model registry, role defaults, adversary cascade |

```bash
# Watch the factory floor (single status + compressed flow + table + inbox)
uv run sweep floor

# Drill into swim lanes
uv run sweep kanban

# QA — standalone activities (no Temporal needed)
uv run sweep qa test    --repo owner/repo --branch fix-x --worktree . --test-cmd 'pytest -x'
uv run sweep qa codex   --repo owner/repo --branch fix-x --worktree .
uv run sweep qa gemini  --repo owner/repo --branch fix-x --worktree . --round 1
uv run sweep qa full    --repo owner/repo --branch fix-x --worktree . --test-cmd 'pytest -x'

# QA — Temporal QaActor (worker must be up)
uv run sweep qa actor signal     # signal QaActor with a fake msg
uv run sweep qa actor status     # query depth + halted
uv run sweep qa actor clear      # clear andon halt

# pr-state
uv run sweep pr-state classify --repo owner/repo --pr 123
uv run sweep pr-state scan --limit 30     # all open PRs → classified.jsonl
uv run sweep pr-state route               # classified.jsonl → per-actor inboxes
uv run sweep pr-state workflow --limit 30 # Temporal one-shot

# Inbox + observability
uv run sweep inbox qa
uv run sweep observe counters
uv run sweep observe events --limit 20
uv run sweep retro status
```

`--help` works at every level: `sweep`, `sweep qa`, `sweep qa actor`. Watch live workflows in the Temporal Web UI at <http://localhost:8233>. Click into a workflow's history to see every activity call, input/output, and the hashed receipt path.

### Bonus: markdown-piped rendering

`sweep floor` and `sweep kanban` emit GitHub-flavored markdown. Same bytes render in three places:

```bash
brew install charmbracelet/tap/glow
uv run sweep floor | glow -      # styled terminal
uv run sweep floor | pbcopy      # paste into a GitHub comment, Notion, anywhere
uv run sweep floor               # plain terminal — still scannable
```

The dual-rendering property is intentional: no second binary, no curses, no lock-in to any viewport.

## Pipeline

```
gh search ──► pr-state ──┬─► QaActor       ──► codex/gemini volley ──► gates
                         ├─► drip inbox       ► close / rebase / ship
                         ├─► respondable      ► human Attend (your inbox)
                         └─► retro            ► audit / SOAP one-pagers
```

`pr-state` runs as a recurring workflow (cron-scheduled), classifies every open authored PR into a bucket, and signals the matching actor with a `Message`. The actor's signal handler dedupes on `msg_id` (idempotent receivers), the workflow processes one message at a time (WIP=1 — the activity signature accepts only one repo + one branch), and posts an ack when done.

### Receipts and attestations

Forgery surface: an LLM agent will happily write `gemini_verdict: "pass"` without calling gemini. The fix is structural — every gate attestation is a hashed pointer to a captured artifact, not a verdict claim.

```python
@dataclass
class GateAttestation:
    verdict: Literal["pass", "fail", "revise", "stubbed"]
    artifact_path: str   # ~/.sweep/attestations/<msg_id>/codex.txt
    sha256: str          # hash of the raw bytes
    verbatim_excerpt: str  # must substring-match artifact contents
    rounds: int
    provenance: str      # "codex" | "opus-fallback" | "haiku-test"
    pinned_head_sha: str | None  # qa gates blow when PR head moves
    pinned_base_sha: str | None  # rebase gates blow when base advances
```

The activity that calls codex/gemini is the only thing that ever writes to the artifact path. The downstream gate-pr-create hook re-hashes the file at push time — mismatch or missing artifact → block. The agent cannot fabricate bytes that hash to a value it doesn't know.

The full chain is in SQLite (`~/.sweep/attestations/llm.db`) with a Merkle-chain `chain_hash` per row. Tampering any past row breaks every subsequent row's hash. `sweep attest verify` walks the chain; concurrent writers are serialized with `BEGIN IMMEDIATE` so the chain can't fork under load.

### Andon (postcondition failures halt the line)

Every activity ends with assertions:

```python
@activity.defn
async def qa_one_entry(req: QaOneEntryRequest) -> QaOneEntryResult:
    ...
    assert result.bugs_found is not None and isinstance(result.bugs_found, int)
    assert Path(result.codex.artifact_path).exists()
    assert Path(result.gemini_last.artifact_path).exists()
    return result
```

Failed assertion → `ApplicationError(non_retryable=True)` → Temporal records the stack trace in workflow history → the actor's signal-handling loop catches it and flips `self.halted = True`. The workflow keeps existing and buffering signals, but stops processing until you send a `clear_andon` signal (after fixing the root cause).

The andon path runs on **every** invocation — there's no dev/prod split for assertions. Pulling the cord is just a test that runs in production. The test scaffolding uses Haiku (variance ~15%) to exercise the assertion paths ~14× more often than Opus would, so by the time you flip to Opus the gate logic is battle-tested.

### Observability — events, counters, cursor

`sweep/observe.py` is the substrate for the forward pass (what happened) and the backward pass (read it back, fold into prescriptions).

- **events.jsonl** — append-only line per mutation. `qa_converged`, `prospect_pass`, `llm_error`, `pipeline_halted` so far.
- **counters.db** — SQLite UPSERT totals: `gh_hit:<endpoint>`, `qa_volley`, `qa_verdict:<bucket>`, `prospect_repos_visited`, `halted_skip:<actor>`.
- **events.cursor** — atomic-written watermark for "retro has read up to here." Retro advances explicitly; forward pass never auto-advances.

```bash
sweep observe counters              # all counters
sweep observe events --limit 20     # tail events.jsonl
sweep observe cursor                # offset + unread count
```

### Retro pager — SOAP one-pagers (the backward pass)

The pipeline writes one SOAP one-pager per cycle to `~/.sweep/retros/`. The cap is 2 files: a third would-be file halts the forward pass until you clear one. Quiet cycles (empty-P rounds) append into the active chain so they don't burn cap slots.

The morphism: `retro file → code/skill changes → git history`. The retro file is ephemeral staging; git is the persistent record of what was acted on. Discard the file once you've committed.

```bash
sweep retro status                  # 0/2 running, 2/2 HALTED, etc.
sweep retro list                    # pending retros
sweep retro show <slug>             # read one
sweep retro discard <slug>          # I've attended; resume forward pass
```

The cap-of-2 is a learning rate matcher: the pipe's improvement rate is bounded by the human's fold rate. The forward pass can't outpace the human's wetware Consolidate.

### Kanban + investigation

Each per-PR workflow tags itself with search attributes (`bucket`, `repo`, `pr`, `msg_id`). The Temporal Web UI gives one-hop investigation: click any card → full event history, activity inputs/outputs, retry traces, signal log.

`sweep floor` is the operator's view (status + flow + table + inbox). `sweep kanban` is the swim-lane drill-down.

## Pipeline stages

| Stage | Actor / workflow | Output |
|-------|-----------------|--------|
| Discover | `prospect` (terminal or scheduled) | `triaged.jsonl` entries |
| Plan repo | `review-schema` skill | repo's gate/signal/tiebreaker profile |
| Triage | `triage` skill | branch + failing test in `~/Documents/<repo>` |
| QA | `QaActor` (Temporal) | gates with hashed receipts; verdict pass/fail |
| Drip | `drip` inbox + skill | staleness check, push, PR created (one per org at a time) |
| Ship | `gh pr create` (gated by hook) | PR open on GitHub |
| Monitor | `pr-state` workflow (recurring) | bucket signal to whichever actor next |
| Retro | `retro` skill + `observe` substrate | SOAP one-pagers → commits → next forward pass |

The Temporal-side coverage is currently `QaActor` + `PrStateWorkflow`. Drip / Triage / Investigate run as skills in terminal mode while the actor wrappers are scoped to land in future passes (see [ROADMAP.md](ROADMAP.md)).

## Rules

- **One PR per org at a time** (org gate enforced by activity).
- **Zero em dashes in any PR text** (validator in drip activity).
- **Read CONTRIBUTING.md** before implementing (triage activity asserts this).
- **Test must fail on main, pass on fix branch** (`test_attestation` is a hard gate).
- **Never `gh pr create` outside `DripActor`** (PreToolUse hook blocks it).
- **Closed is closed** — no retroactive adjustments to merge rate.
- **Haiku for test scaffolding, never for production judgment** (env-var gated).

## PR Quality Gate

Protect your repo against AI slop. Same checks this pipeline enforces on itself, packaged as a GitHub Action for maintainers.

### What it checks

| Check | What it catches |
|-------|-----------------|
| **Em dashes** | Strongest single signal for AI-generated prose |
| **Description depth** | PR describes *what* changed instead of *why* it's correct. Claude Haiku judges (~$0.001/PR) |
| **CONTRIBUTING compliance** | Wrong branch, too many commits, AI policy violations |
| **Test presence** | Bug fix with no tests is an unproven claim |
| **Contributor velocity** | 5+ PRs in 24h across GitHub is a spray pattern |

First-time contributors (< 3 prior merges): any warning auto-closes the PR. Established contributors (3+ merges): warnings are advisory. Standing is earned, not assumed.

### Install

Add to `.github/workflows/pr-gate.yml`:

```yaml
name: PR Quality Gate
on:
  pull_request:
    types: [opened, edited, synchronize]

permissions:
  pull-requests: write
  contents: read

jobs:
  quality-gate:
    runs-on: ubuntu-latest
    steps:
      - uses: kimjune01/sweep@master
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}  # required, ~$0.001/PR
```

---

*Licensed [CC BY-SA-NS](LICENSE.md) — CC BY-SA 4.0 plus a network-services clause. Build on it freely; if you serve it, source flows to users.*
