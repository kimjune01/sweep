# Sweep

Two tools, same repo.

**For contributors:** Contribute to open source at scale. A Temporal-supervised pipeline finds maintainer-acknowledged bugs, writes failing tests, implements fixes, runs adversarial code review, and queues PRs at a pace that builds standing instead of getting banned. One PR per org at a time, every gate has a hashed receipt, andon halts the line when a postcondition fails.

**For maintainers:** [Protect your repo against AI slop.](#pr-quality-gate) Same checks the pipeline enforces on itself, packaged as a GitHub Action. Advisory, not blocking.

## What it does

Scans GitHub for repos with acknowledged bugs, picks the actionable ones, writes failing tests and minimal fixes, runs codex + gemini as adversarial reviewers, captures each reviewer's raw response as a tamper-evident receipt, and ships through a paced drip queue. The supervisor (a Temporal workflow) restarts crashed work, halts on contract violations, and exposes a deep-linked Web UI for one-hop investigation when something goes wrong.

## Architecture

```
                  ┌────────────────────────────────────────┐
                  │           GitHub (the world)            │
                  └─────────────────┬──────────────────────┘
                                    │ gh / API
                                    ▼
                  ┌─────────────────────────────────────────┐
                  │  pr-state workflow (classifier/dispatcher) │
                  │  buckets: qa | investigate | rebase | …  │
                  └────────┬─────────┬──────────┬────────────┘
                           │ signal  │ signal   │ signal
                           ▼         ▼          ▼
                  ┌──────────┐ ┌──────────┐ ┌──────────┐
                  │ QaActor  │ │  Drip    │ │ Investig.│  (long-running workflows)
                  │  WIP=1   │ │  WIP=1   │ │  WIP=1   │
                  └────┬─────┘ └────┬─────┘ └────┬─────┘
                       │            │            │
                       ▼            ▼            ▼
                  ┌─────────────────────────────────────┐
                  │  Activities — typed, asserted        │
                  │  test_attestation, codex_review,     │
                  │  gemini_review, qa_one_entry, …      │
                  │  Each writes a hashed receipt to     │
                  │  ~/.sweep/attestations/<msg_id>/     │
                  └─────────────────────────────────────┘
```

Two operational modes:

| Mode | When | Substrate |
|------|------|-----------|
| **Terminal** | Manual dev / debug one entry / experiment | Markdown skills in `~/.claude/skills/` invoked from a Claude session. No Temporal. State files written directly to `~/.sweep/`. |
| **Hyper-supervision** | Unattended autonomous runs | Temporal server + Python worker. Workflows orchestrate, activities execute, history is the audit log. No long-running Claude session. |

Skills and Python activities share the same contract — one `msg_id`, one repo, one branch, gates produced with hashed artifacts — so the two modes are interchangeable per entry, not per pipeline. Skills are useful for ad-hoc; production runs through Temporal.

## Prerequisites

- [Claude Code](https://claude.ai/code) installed
- `gh auth status` passes
- `uv` ([installation](https://docs.astral.sh/uv/getting-started/installation/))
- `temporal` CLI ([installation](https://docs.temporal.io/cli)) — single binary, `temporal server start-dev` is enough
- `ANTHROPIC_API_KEY` set in env (for Haiku-in-tests; Opus/Sonnet for prod)
- `OPENAI_API_KEY` set in env (for codex review)
- A working directory you don't mind cloning repos into (`~/Documents/` by default)

## Quick start

Sweep keeps its state at `~/.sweep/`. The git repo at `~/Documents/sweep/` holds the code. They're separate by design — don't clone this repo into `~/.sweep`.

### 1. Install the code

```bash
git clone https://github.com/kimjune01/sweep ~/Documents/sweep
cd ~/Documents/sweep
uv sync
```

### 2. Create state directory

```bash
mkdir -p ~/.sweep/{attestations,inbox}
ln -s ~/Documents/sweep/bin ~/.sweep/bin
ln -s ~/Documents/sweep/templates ~/.sweep/templates
```

### 3. Install the skills (terminal mode)

```bash
for skill in actionable drip investigate qa retro review-schema sweep triage pr-state; do
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
uv run python -m sweep.worker
```

The worker registers the `QaActor` workflow + activities against task queue `qa-tq` and waits for signals.

### 5. Send a synthetic message

```bash
uv run python -m sweep.client --synthetic
```

Watch the workflow in the Web UI. Click into its history to see every activity call, input, output, and the hashed receipt path for the captured LLM responses.

## Pipeline

```
gh search ──► pr-state ──┬─► QaActor       ──► codex/gemini volley ──► gates
                         ├─► InvestigateActor ► respond to reviewer
                         ├─► DripActor       ► close / rebase / ship
                         └─► retro            ► audit only (wait bucket)
```

Each `Actor` is a long-running Temporal workflow. `pr-state` runs as a recurring workflow (cron-scheduled), classifies every open authored PR into a bucket, and signals the matching actor with a `Message`. The actor's signal handler dedupes on `msg_id` (idempotent receivers), the workflow processes one message at a time (WIP=1 — the activity signature accepts only one repo + one branch), and posts an ack when done.

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
```

The activity that calls codex/gemini is the only thing that ever writes to the artifact path. The downstream gate-pr-create hook re-hashes the file at push time — mismatch or missing artifact → block. The agent cannot fabricate bytes that hash to a value it doesn't know.

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

### Kanban + investigation

Each per-PR workflow tags itself with search attributes (`bucket`, `repo`, `pr`, `msg_id`). A kanban view is just `client.list_workflows("WorkflowType='PrPipeline'")` grouped by `bucket`. Click any card → land on the Temporal Web UI page for that workflow execution → full event history, activity inputs/outputs, retry traces, signal log. O(1) investigation.

## Pipeline stages

| Stage | Actor / workflow | Output |
|-------|-----------------|--------|
| Discover | `actionable` (terminal mode) or scheduled crawl | `repos.jsonl` entries |
| Plan repo | `review-schema` workflow | repo's gate/signal/tiebreaker profile |
| Triage | `TriageActor` | branch + failing test in `~/Documents/<repo>` |
| QA | `QaActor` | gates with hashed receipts; verdict pass/fail |
| Drip | `DripActor` | staleness check, push, PR created (one per org at a time) |
| Ship | `gh pr create` (gated by hook) | PR open on GitHub |
| Monitor | `pr-state` (recurring) | bucket signal to whichever actor next |
| Retro | `retro` batch workflow | parameter updates feeding back into `actionable` scoring |

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
