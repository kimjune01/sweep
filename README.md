# Sweep

Contribute to open source at scale. Claude Opus orchestrates, Codex implements, Gemini gates. Finds issues, writes fixes, ships PRs — one per org, quality-gated.

## What it does

Scans GitHub for repos with maintainer-acknowledged bugs, writes failing tests, implements fixes, runs adversarial code review, and queues PRs at a pace that builds standing instead of getting banned.

## Checklist

Before you paste the setup prompt below into Claude Code:

- [ ] [Claude Code](https://claude.ai/code) installed (Opus model required — orchestration is judgment-heavy)
- [ ] `gh auth status` passes (GitHub CLI authenticated)
- [ ] `jq` installed (`brew install jq` or `apt install jq`)
- [ ] `gemini` CLI installed ([google-gemini/gemini-cli](https://github.com/google-gemini/gemini-cli))
- [ ] `OPENAI_API_KEY` set in environment (for `/codex` crosscheck)
- [ ] A working directory you don't mind cloning repos into (`~/Documents/` by default)

## Setup

Do not clone this repo. The pipeline state (drip queues, repos.jsonl, gate files) is per-machine and will conflict. Copy the prompt below into Claude Code and run it — it creates everything from scratch.

---

Set up the sweep pipeline on this machine. Create the following directory structure and files exactly as specified. Do not skip any file.

### 1. Directory structure

```
mkdir -p ~/.sweep/{bin,drip-queue,repos,gates,retro,actionable,cooldown}
```

### 2. config.json

Write to `~/.sweep/config.json`:
```json
{"concurrency": 5, "dry_run": true}
```

### 3. repos.jsonl

Write an empty file at `~/.sweep/repos.jsonl`. This is the repo roster — append-only, one JSON object per line.

### 4. SWEEP_LOG.md

Write to `~/.sweep/SWEEP_LOG.md`:
```
# Sweep Log
```

### 5. bin/tick.py

Write to `~/.sweep/bin/tick.py` and `chmod +x` it. This is the pipeline status display.

```python
#!/usr/bin/env python3
"""Pipeline tick. Reads drip queues, prints bucket chain, auto-advances qa_passed entries where org gate is clear."""

import json, os, glob, sys, subprocess
from collections import defaultdict
from datetime import datetime, timezone

drip_dir = os.path.expanduser("~/.sweep/drip-queue")
repos_file = os.path.expanduser("~/.sweep/repos.jsonl")
state_file = os.path.expanduser("~/.sweep/bin/.tick_state.json")

def attested(e):
    g = e.get("gates", {})
    return isinstance(g.get("bugs_found"), int)

sc = defaultdict(int)
demoted = 0
all_qa = []

for f in glob.glob(os.path.join(drip_dir, "*.jsonl")):
    issues = {}
    for line in open(f):
        line = line.strip()
        if not line: continue
        try:
            e = json.loads(line)
            key = e.get("issue", e.get("branch", "?"))
            issues[str(key)] = e
            if "branch" in e:
                issues[e["branch"]] = e
        except: pass
    seen = set()
    for key, e in issues.items():
        eid = id(e)
        if eid in seen: continue
        seen.add(eid)
        status = e.get("status", "?")
        if status == "qa_passed" and not attested(e):
            sc["queued"] += 1
            demoted += 1
        else:
            sc[status] += 1
            if status == "qa_passed" and attested(e):
                repo = e.get("repo", "")
                org = repo.split("/")[0] if "/" in repo else ""
                all_qa.append((f, key, e, org))

rs = {}
if os.path.exists(repos_file):
    for line in open(repos_file):
        try:
            e = json.loads(line.strip())
            rs[e["repo"]] = e
        except: pass

r = sum(1 for e in rs.values() if e.get("status") == "ready")
q = sc.get("queued", 0) + sc.get("ready", 0) + sc.get("triaged", 0)
qa = sc.get("qa_passed", 0)
d = sc.get("dripped", 0)
s = sc.get("shipped", 0)
m = sc.get("merged", 0)

mode = sys.argv[1] if len(sys.argv) > 1 else "dry-run"
prev = {}
if os.path.exists(state_file):
    try: prev = json.load(open(state_file))
    except: pass
tick = prev.get("tick", 0) + 1

print(f"tick {tick} [{mode}]")
print(f"  ready[{r}] -> triaged[{q}] -> qa[{qa}] -> dripped[{d}] -> shipped[{s}] -> merged[{m}]")

json.dump({"tick": tick, "r": r, "q": q, "qa": qa, "d": d, "s": s, "m": m}, open(state_file, "w"))
```

### 6. bin/org-gate

Write to `~/.sweep/bin/org-gate` and `chmod +x` it. Checks if an org slot is available for a new PR.

```bash
#!/usr/bin/env bash
set -euo pipefail
repo="${1:?Usage: org-gate <owner/repo>}"
org="${repo%%/*}"
# Check if you have any open PRs in this org
OPEN=$(gh search prs --author="$(gh api user --jq .login)" --state=open --limit=100 --json repository --jq "[.[] | select(.repository.nameWithOwner | startswith(\"$org/\"))] | length" 2>/dev/null || echo "0")
if [ "$OPEN" -gt 0 ]; then
  echo "{\"verdict\": \"blocked\", \"org\": \"$org\", \"open\": $OPEN}"
else
  echo "{\"verdict\": \"clear\", \"org\": \"$org\"}"
fi
```

### 7. hooks/gate-pr-create.sh

Write to `~/.claude/hooks/gate-pr-create.sh` and `chmod +x` it. This is a pre-tool-use hook that blocks `gh pr create` unless a gate attestation file exists.

```bash
#!/bin/bash
INPUT=$(cat)
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)
[ -z "$CMD" ] && exit 0

STRIPPED=$(echo "$CMD" | sed "s/'[^']*'//g" | sed 's/"[^"]*"//g')
if echo "$STRIPPED" | grep -qE 'gh[[:space:]]+pr[[:space:]]+create'; then
  REPO=$(echo "$CMD" | grep -oE '\-\-repo[= ][A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+' | head -1 | sed 's/--repo[= ]*//')
  [ -z "$REPO" ] && { echo "BLOCKED: gh pr create missing --repo flag." >&2; exit 2; }
  GATE_FILE="$HOME/.sweep/gates/${REPO//\//-}.gate"
  [ ! -f "$GATE_FILE" ] && { echo "BLOCKED: no gate file at $GATE_FILE. Run /drip first." >&2; exit 2; }
  for field in gemini_verdict gemini_first gemini_last codex_verdict test_attestation; do
    val=$(jq -r ".$field // empty" "$GATE_FILE" 2>/dev/null)
    [ -z "$val" ] && { echo "BLOCKED: gate file missing $field." >&2; exit 2; }
  done
  rm "$GATE_FILE"
fi
exit 0
```

Then register it in `.claude/settings.json` under hooks:
```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/gate-pr-create.sh"
          }
        ]
      }
    ]
  }
}
```

### 8. Skills

Fetch each skill and install it. Each link is the raw skill definition:

- [sweep](https://github.com/kimjune01/sweep/blob/master/skills/sweep.md) — multi-repo orchestrator
- [triage](https://github.com/kimjune01/sweep/blob/master/skills/triage.md) — per-repo investigation + implementation
- [qa](https://github.com/kimjune01/sweep/blob/master/skills/qa.md) — adversarial code review (gemini + codex)
- [drip](https://github.com/kimjune01/sweep/blob/master/skills/drip.md) — process gates (staleness, org gate, tone)
- [ship](https://github.com/kimjune01/sweep/blob/master/skills/ship.md) — PR creation (only path to `gh pr create`)
- [actionable](https://github.com/kimjune01/sweep/blob/master/skills/actionable.md) — find repos worth contributing to
- [retro](https://github.com/kimjune01/sweep/blob/master/skills/retro.md) — compress outcomes into durable artifacts
- [review-schema](https://github.com/kimjune01/sweep/blob/master/skills/review-schema.md) — induce repo review culture

```bash
for skill in sweep triage qa drip ship actionable retro review-schema; do
  mkdir -p ~/.claude/skills/"$skill"
  curl -sL "https://raw.githubusercontent.com/kimjune01/sweep/master/skills/${skill}.md" \
    -o ~/.claude/skills/"$skill"/skill.md
done
```

The skills reference `/codex` and `/gemini` for adversarial code review. These are separate skills that call external models:
- `/codex` sends code to OpenAI's GPT-5.5 (codex) for structural review. Requires `OPENAI_API_KEY`.
- `/gemini` sends code to Google's Gemini for logic tracing. Requires `gemini` CLI installed.

Both are required. The gate hook blocks shipping without attestations from both. This is not optional — session 4 shipped 22 PRs without review and 27% had bugs. The gates exist because skipping them was tried and it failed.

### 9. Verify

Run `python3 ~/.sweep/bin/tick.py` — should print:
```
tick 1 [dry-run]
  ready[0] -> triaged[0] -> qa[0] -> dripped[0] -> shipped[0] -> merged[0]
```

### 10. First run

Start with `/actionable` to seed your repo roster, then `/sweep --dry-run` to triage without shipping. Review the branches before removing `--dry-run`.

---

## Pipeline

```
/actionable -> repos.jsonl -> /sweep -> /triage (per repo) -> /qa -> /drip -> /ship
                                                    |              |         |
                                               branch + test   gate file   gh pr create
```

One PR per org at a time. Quality gates block shipping until gemini + codex + tests all pass. The gate hook enforces this — no gate file, no PR.

## Rules

- One PR per org at a time (org gate)
- Zero em dashes in any PR text
- Read CONTRIBUTING.md before implementing
- Test must fail on main, pass on fix branch
- Never `gh pr create` outside of `/ship`
- Closed is closed — no adjustments to merge rate

---

## PR Quality Gate

Protect your repo against AI slop. Same checks this pipeline enforces on itself, packaged as a GitHub Action for maintainers.

### What it checks

| Check | What it catches |
|-------|-----------------|
| **Em dashes** | Strongest single signal for AI-generated prose |
| **Description depth** | PR describes *what* changed instead of *why* it's correct. Uses Claude Haiku (~$0.001/PR) when API key provided, keyword heuristics otherwise |
| **CONTRIBUTING compliance** | Wrong branch, too many commits, AI policy violations |
| **Test presence** | Bug fix with no tests is an unproven claim |
| **Contributor velocity** | 5+ PRs in 24h across GitHub is a spray pattern |

Advisory only. Posts a comment, does not block merging.

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
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}  # optional, enables LLM description check
```
