---
name: triage
description: Compress one repo's open issues/PRs into a punch list of investigatable branches. Score the items, kill the unactionable, fan out one /investigate per survivor, hand the branches to /drip. Worktree count returns to zero at stage end (harness asserts).
argument-hint: <repo> [--limit N] [--concurrency N] [--label LABEL] [--dry-run]
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, Agent
---

# Triage

You were invoked by the harness on one repo. Compress three repeated episodes into one pass:

- The hour spent staring at issue lists looking for actionable bugs → seconds of scoring.
- The investigations into items that were never going to merge → kill list rejects them upfront.
- The serial slog of N investigations → N parallel agents, shared graph for dedup.

What's lost: the contingent details of each item (specific labels, prior comment threads, hardware specifics). Kept: which signal applies, which kill reason matches, which graph node to fan into. The loss is what didn't generalize.

Run `/review-schema` once per repo before first triage. Without it, your investigations produce PRs that don't match the maintainer's review culture.

## The CLI is the harness

| What you need | How to get it |
|---|---|
| Fetch open issues/PRs incrementally since last scan | `sweep triage scan --repo …` |
| Competing-PR / body-count check on one issue | `sweep triage compete --repo … --issue N` |
| Retro params for the repo | `sweep retro params --repo …` |
| Enqueue a branch pointer for drip | `sweep drip enqueue --repo … --branch … --issue N --test-cmd "…" --base SHA` |
| Resume: state of each item across runs | `sweep triage status --repo …` |
| Spawn an investigation agent | Agent tool, prompt in *Spawn one agent per survivor* below |

Call the CLI subcommand you need even if it doesn't exist yet. The harness logs the missing reach to `sweep missing`; that's the build queue (see [JIT CLI](https://june.kim/jit-cli)). Don't hand-roll the gh+jsonl glue here.

## Score each item (highest signal wins)

| Signal | Score | Rationale |
|--------|-------|-----------|
| CI failing on your PR | 10 | Blocking, fix before review |
| Reviewer requested changes | 8 | Someone spent time; respond |
| Maintainer commented on your item | 7 | Engagement with merge power |
| LGTM but needs rebase | 6 | Low effort to unblock |
| Your PR, no activity > 3 days | 4 | Might need a ping |
| Issue you filed | 3 | Your problem to solve |
| Maintainer-filed issue | 2+ | They want it. **Penalty if "good first issue"**: fast claimers race you. Unlabeled bugs nobody noticed are better targets. |
| Unassigned open issue | 2 | Opportunity |
| Your PR, CI passing, under review | 1 | Wait |

## Kill list (don't even score)

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
| Heuristic / perf tuning without device-diverse CI | Can't validate. geohot: "no on all heuristic changes" |
| Net-addition perf optimization | "We never trade complexity for speed" |
| Requires off-platform discussion | Pipeline only speaks GitHub |

## Spawn one agent per survivor

Each survivor gets its own worktree. Spawn the agent in parallel. The agent runs `/investigate` to a terminal node, calls `sweep drip enqueue` if CONFIRMED, removes its worktree, returns.

```
Agent({
  subagent_type: "general-purpose",
  run_in_background: true,
  prompt: "Run /investigate on <repo>#<issue>. Context: <diff/body/comments/prior-failed-PRs>.
           Worktree: <path>. Read TRIAGE_GRAPH.md for cross-investigation context.
           Write your results to TRIAGE_RESULT.T<issue>.md.
           Test before fix: failing test on master, passing on fix.
           On CONFIRMED: call `sweep drip enqueue`. On any terminal status
           (CONFIRMED / KILLED / BLOCKED): remove your worktree before returning."
})
```

**Postcondition: zero `triage-*` worktrees after triage finishes.** The harness asserts at stage end and fails with the list of leaked paths. The assertion is the binding; don't write the cleanup rule into prose hoping it sticks (see [skills lack determinism](https://june.kim/skills-lack-determinism)). If the postcondition fails, the failure names the path that didn't clean up. That's your debug surface.

The agent's context must include the item's diff or body, CI logs, review comments, related nodes in TRIAGE_GRAPH.md, and **prior failed PRs on the same issue**. Three failed PRs means three mapped failure modes; the fourth attempt avoids all three.

## Gemini volley on the kill decisions

After scoring and killing, send the scan table to `/gemini`:

> Review these triage decisions. Any items killed that should be investigated? Any items kept that are a waste of time? Any cross-references missed?

Five rounds max. The volley won't converge to zero findings (see [does iteration mitigate slop slope](https://june.kim/does-iteration-mitigate-slop-slope)). Iterate until the structure is sound, then move on.

## Fast-path for retro-confirmed fixes

If `sweep retro params --repo` returns a `fix_ready` entry for an issue (one-line fix with a confirmed reproducer), skip the investigation. Mark CONFIRMED and call `sweep drip enqueue` directly. The retro already did the compression for you.

## TRIAGE_GRAPH.md

Shared scratch across investigations. Each agent reads it at spawn time to dedup against other agents' findings, then writes its own results to `TRIAGE_RESULT.T<n>.md` (per-item file; no concurrent writes to the shared graph). Phase boundaries merge result files into the shared graph sequentially.

Don't lock down the graph format. The CLI owns the queue; the graph is for the agents to shape as the investigations evolve.

## Rules (judgment, not mechanics)

- **Never merge.** Triage produces branches; the human ships.
- **Score before investigating.** Don't spend agent time on items scoring 1.
- **Cross-pollinate.** If agent A finds something that affects agent B's item, write to the graph before B's next perturbation.
- **Full pipeline per item.** Every candidate passes `/codex` (structural) and `/bug-hunt` (adversarial) before enqueueing. No shortcuts.
- **Fail fast.** Item at depth 3 with all hypotheses killed → BLOCKED, move on.
- **Fail on master, pass with fix.** Every PR's load-bearing assertion. The CLI gate (`sweep qa test`) enforces it; if it rejects, re-investigate, don't bypass.

## What this skill does not do

- Read or write `~/.sweep/drip-queue/*.jsonl` directly. (`sweep drip enqueue`.)
- Parse `TRIAGE_GRAPH.md` state machines for resume. (`sweep triage status`.)
- Manage worker-pool concurrency by hand. (Spawn N parallel agents; throttle via `sweep pause`.)
- Track who cleans up which worktree. (Harness postcondition catches leaks.)
- Define what counts as a terminal status. (Same enum as `/investigate`; the CLI owns it.)
- Create PRs, push branches, or write PR descriptions. (`/drip`.)
