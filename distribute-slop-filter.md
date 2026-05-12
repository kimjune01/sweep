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

## Search strategies

Run all of these, pool and dedup results:

```bash
# 1. CONTRIBUTING.md with AI/LLM policy language
gh api 'search/code?q=%22LLM%22+%22do+not%22+filename:CONTRIBUTING.md&per_page=20' \
  --jq '.items[].repository.full_name'

gh api 'search/code?q=%22AI+generated%22+%22not+accepted%22+filename:CONTRIBUTING.md&per_page=20' \
  --jq '.items[].repository.full_name'

gh api 'search/code?q=%22ai-slop%22+filename:CONTRIBUTING.md&per_page=20' \
  --jq '.items[].repository.full_name'

# 2. AGENTS.md with refusal language
gh api 'search/code?q=%22do+NOT%22+filename:AGENTS.md&per_page=20' \
  --jq '.items[].repository.full_name'

# 3. Repos using known AI PR detection actions
gh api 'search/code?q=%22agentscan%22+filename:.yml+path:.github/workflows&per_page=20' \
  --jq '.items[].repository.full_name'

# 4. Issues/PRs mentioning AI slop problems
gh search issues "AI generated PRs" --sort reactions --json repository --jq '.[].repository.fullName' | head -20
gh search issues "LLM spam PRs" --sort reactions --json repository --jq '.[].repository.fullName' | head -20
```

## Filter

For each candidate repo:
1. Skip if in `~/.sweep/banlist.txt`
2. Skip if already has an issue from kimjune01 about AI PRs
3. Skip if repo has <100 stars (not worth the noise)
4. Skip if repo is archived
5. Verify the repo actually has the problem (check recent closed PRs for AI patterns, or confirm the policy file exists)

## Dispatch

```bash
# --dry-run: report only
~/.sweep/bin/offer-slop-filter --dry-run <owner/repo>

# live: open the issue
~/.sweep/bin/offer-slop-filter <owner/repo>
```

`--dry-run` passed to `/slop-filter` propagates to every `offer-slop-filter` call.

Default `--limit` is 10 repos per run.

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
