---
name: distribute-slop-filter
description: Find repos struggling with AI-generated PRs and offer the quality gate action. Independent of the main sweep pipeline.
argument-hint: [--dry-run] [--limit N]
allowed-tools: Bash, Read, Write
user_invocable: true
---

# Slop Filter

Find repos that are actively dealing with AI-generated PRs and offer the quality gate action. Runs independently of sweep/triage/actionable.

## What it does

1. Search GitHub for repos with anti-AI policies or evidence of AI PR problems
2. For each, check banlist and dedup
3. Open an issue offering `kimjune01/sweep`'s PR Quality Gate action
4. Log results

## Search strategy

Top repos by stars, descending. Bigger repos get more AI slop. The evidence filter (5+ catchable PRs/week) does the qualification, not policy detection.

```bash
# Sharded by star range to bypass GitHub's 1000-result cap.
# Each shard sorted by stars desc, up to 1000 results.
SHARDS=(
  "stars:>100000"
  "stars:50000..100000"
  "stars:20000..50000"
  "stars:10000..20000"
  "stars:5000..10000"
)

for shard in "${SHARDS[@]}"; do
  gh api "search/repositories?q=${shard}+is:public&sort=stars&order=desc&per_page=100" \
    --jq '.items[] | select(.has_issues and .archived == false and .fork == false) | .full_name'
done
```

One shard per tick. The cursor JSONL tracks which shard we're in. ~500 repos in the >100K shard, ~2000 in 5K-10K. Total space is ~8K repos.

Walk the list top to bottom. For each, run `offer-slop-filter` which checks evidence (5+ catchable PRs in the last week). Most repos won't qualify. The ones that do are the ones drowning.

State file: `~/.sweep/slop-filter-cursor.jsonl` — append-only, one line per repo checked.

```jsonl
{"ts":"2026-05-13T00:00:00Z","repo":"torvalds/linux","stars":195000,"result":"skip","reason":"0 catchable"}
{"ts":"2026-05-13T00:00:01Z","repo":"facebook/react","stars":190000,"result":"offered","issue":"https://github.com/..."}
```

Each run reads the file, skips already-checked repos, continues from the highest-star unchecked repo.

## Filter

For each candidate repo:
1. Skip if in `~/.sweep/banlist.txt`
2. Skip if already has an issue from kimjune01 about AI PRs
3. Skip if repo has <1000 stars (smaller repos don't get enough AI slop to justify the action)
4. Skip if repo is archived
5. Skip if issues are disabled
6. `offer-slop-filter` checks: would the filter have caught 5+ PRs in the last week? If not, skip. The problem must be bad enough to justify installing an action.

Sort candidates by star count descending. Bigger repos get hit harder by AI slop.

## Dispatch

Each tick has two phases — withdraw first (cleanup), offer second (new sends).

```bash
# Phase 1: withdraw stale silent issues (politeness — clears maintainer noise debt)
# Closes our open issues that got the silent treatment for 2+ days with zero
# engagement (no comments, no reactions). Posts a polite withdrawal comment
# before closing. Reactions (👀, 👍) protect an issue from withdrawal.
~/.sweep/bin/offer-slop-filter --withdraw-stale [--dry-run] [--age 2]

# Phase 2: offer to new candidates
~/.sweep/bin/offer-slop-filter [--dry-run] <owner/repo>
```

**Why withdraw first.** Issues we left silent are accumulating maintainer noise debt.
A 2-day silence is the maintainer telling us "I saw your offer and chose to ignore."
Closing it ourselves is polite — they don't have to spend the click. It also keeps
the scoreboard's silent-treatment-as-negative bucket from growing past the
[2-day politeness threshold](#).

`--dry-run` passed to `/slop-filter` propagates to every `offer-slop-filter` call,
both phases.

Default `--limit` is 10 repos per run (offer phase only — withdrawal sweeps all
stale silent issues unconditionally).

## Output

Print a table:

```
OFFERED
  dolphin-emu/dolphin     #1234  https://github.com/...
  keras-team/keras        #5678  https://github.com/...

SKIPPED (banned)
  kanidm/kanidm

SKIPPED (already offered)
  MonoGame/MonoGame       #999

SKIPPED (archived / low stars)
  some/repo
```

Log all offered repos to `~/.sweep/actionable/candidates.jsonl` with `action: "slop_filter_offered"`.
