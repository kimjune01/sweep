---
name: triage
description: Scan a repo's open issues/PRs, score and kill, spawn one investigation per surviving item, hand the resulting branches to /drip. Judgment lives here; queue state, gh fetches, resume, and idempotency live in `sweep` CLI.
argument-hint: <repo> [--limit N] [--concurrency N] [--label LABEL] [--dry-run]
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, Agent
---

# Triage: Repo to Drip Queue

You were invoked by the harness on one repo. Score the open items, kill the unactionable ones, spawn `/investigate` on the survivors, and hand the resulting branches to `/drip`. The judgment about *what's worth investigating* and *how to spawn an investigation* is the LLM-shaped part — that's this skill. Everything else (queue state, gh fetches with the right `--search`, retro params, resume, idempotency) belongs in `sweep` CLI; call it.

Run `/review-schema` once per repo before first triage. Without the schema, agents produce PRs that don't match the maintainer's perceive loop.

## The CLI is the harness

| What you need | How to get it |
|---|---|
| Fetch open issues/PRs (incremental since last scan) | `sweep triage scan --repo …` *(returns JSON list; harness handles `repos.jsonl` cursors)* |
| Competing-PR / body-count check on one issue | `sweep triage compete --repo … --issue N` |
| Retro params for the repo | `sweep retro params --repo …` |
| Enqueue a branch pointer for drip | `sweep drip enqueue --repo … --branch … --issue N --test-cmd "…" --base <sha>` |
| Check current state of an item (resume) | `sweep triage status --repo … --issue N` |
| Spawn an investigation agent | `Agent(subagent_type: "general-purpose", prompt: "Run /investigate on …", ...)` |

If a `sweep` subcommand isn't there yet, that's a CLI gap to add — don't hand-roll the gh+jsonl logic in this skill. The deterministic harness rejects malformed inputs with errors you can [close the loop](https://june.kim/skills-lack-determinism) on.

> The judgment on *what command to call* is yours. The queue arithmetic is not. [Don't LLM what you can code.](https://june.kim/dont-lang-what-you-can-math)

## The judgment part

### Score each item (highest signal wins)

| Signal | Score | Rationale |
|--------|-------|-----------|
| CI failing on your PR | 10 | Blocking — fix before review |
| Reviewer requested changes | 8 | Someone spent time; respond |
| Maintainer commented on your item | 7 | Engagement with merge power |
| LGTM but needs rebase | 6 | Low effort to unblock |
| Your PR, no activity > 3 days | 4 | Might need a ping |
| Issue you filed | 3 | Your problem to solve |
| Maintainer-filed issue | 2+ | They want it. **Penalty if "good first issue"** — fast claimers race you. Unlabeled bugs nobody noticed are better targets. |
| Unassigned open issue | 2 | Opportunity |
| Your PR, CI passing, under review | 1 | Wait |

### Kill list (don't even score)

| Kill signal | Reason |
|---|---|
| Needs hardware you don't own and CI doesn't have | Can't reproduce |
| Feature request with no maintainer endorsement | Inventing problems |
| Design proposal / TIP (unless you're core) | Architecture is maintainer's call |
| Vague, no repro, no error | Nothing to test |
| Already fixed on master | Verify and close |
| Someone else has an open PR | Don't compete; link to theirs |
| Tracking / milestone issue | Not actionable |
| Cooldown active (check retro params) | You were warned or banned |
| Heuristic / performance tuning without device-diverse CI | Can't validate. geohot: "no on all heuristic changes" |
| Net-addition perf optimization | "We never trade complexity for speed" |
| Requires off-platform discussion | Pipeline only speaks GitHub |

### Spawn one agent per survivor

```
Agent({
  subagent_type: "general-purpose",
  run_in_background: true,
  prompt: "Run /investigate on <repo>#<issue>. Context: <diff/body/comments/prior-failed-PRs>.
           Read TRIAGE_GRAPH.md. Write your results to TRIAGE_RESULT.T<issue>.md.
           Test before fix: failing test on master, passing on fix. After investigation,
           call `sweep drip enqueue` with your branch."
})
```

Each agent writes to its own `TRIAGE_RESULT.T<n>.md` (no parallel-write conflict on the shared graph). Merge into `TRIAGE_GRAPH.md` after agents finish.

**Context for the agent must include:** diff/body, CI logs, review comments, related nodes in `TRIAGE_GRAPH.md`, and **prior failed PRs** (`gh pr list --search "<issue>" --state closed` — what was rejected and why). Three failed PRs on the same issue means three mapped failure modes. The next attempt avoids all three.

### Gemini volley on the kill decisions

After scoring + killing, send the scan table to `/gemini`:

> Review these triage decisions. Any items killed that should be investigated? Any items kept that are a waste of time? Any cross-references missed?

Apply feedback, re-send. Five rounds max. The volley [won't converge to zero findings](https://june.kim/does-iteration-mitigate-slop-slope) — iterate until structure is sound, then move on.

### Fast-path for retro-confirmed fixes

If `sweep retro params --repo` returns a `fix_ready` entry for an issue (1-liner with confirmed reproducer), skip investigation: mark CONFIRMED and call `sweep drip enqueue` directly.

## TRIAGE_GRAPH.md

The shared coordination file. Per item: hypothesis nodes (T\<issue>.H\<n>), cross-references between items, statuses (PENDING / IN_PROGRESS / CONFIRMED / KILLED / BLOCKED / SHIPPED / SKIP). Agents read it at spawn to dedup against other agents' findings. Phase boundaries merge per-item result files into it sequentially — no concurrent writes.

## Rules (judgment, not mechanics)

- **Never merge.** Triage produces branches; the human ships.
- **Score before investigating.** Don't waste agent time on items that score 1.
- **Cross-pollinate.** If agent A finds something that affects agent B's item, write it to the graph before agent B's next perturbation.
- **Full pipeline per item.** Every candidate must pass `/codex` (structural) and `/bug-hunt` (adversarial) before enqueueing. No shortcuts.
- **Fail fast.** Item at depth 3 with all hypotheses killed and no new edges → BLOCKED. Move on.
- **Fail on master, pass with fix.** This is the assertion every PR makes. The CLI gate (`sweep qa test`) enforces it; if it rejects you, don't bypass — re-investigate.

## What this skill does not do

- Read or write `~/.sweep/drip-queue/*.jsonl` directly. (`sweep drip enqueue` does.)
- Implement resume by re-parsing `TRIAGE_GRAPH.md` state machines. (Agents are idempotent on item id; `sweep triage status` tells you what's already done.)
- Manage worker-pool concurrency by hand. (Spawn N agents in parallel via the Agent tool; the harness throttles via `sweep control pause` if needed.)
- Create PRs, push branches, write PR descriptions. (`/drip` does, downstream.)
- Format scan tables or define status enums. (Harness owns the schema; this skill writes prose findings to `TRIAGE_GRAPH.md`.)
