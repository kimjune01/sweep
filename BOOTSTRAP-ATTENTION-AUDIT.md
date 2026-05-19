# Bootstrap: audit actors against the human-attention principle

Paste this prompt (or invoke as a skill) to walk every substrate actor
and surface paths that violate `HUMAN_ATTENTION_PRINCIPLE.md`. Produces
a per-actor table of findings, prioritized by how much human attention
the violation wastes.

## Setup

Read first:
- `/Users/junekim/Documents/sweep/HUMAN_ATTENTION_PRINCIPLE.md` —
  the principle itself
- `/Users/junekim/Documents/sweep/sweep/activities/*.py` — the actors
- `/Users/junekim/Documents/sweep/sweep/workflows/*.py` — the workflow
  shells (qa_actor.py, skill_actor.py, etc.)
- `/Users/junekim/Documents/sweep/sweep/pokayoke.py` — intake contracts

Inventory the actors. As of 2026-05-19 the set is roughly:
scout, sift, rope, triage, investigate, reinvestigate, switch, qa,
reqa, attest, compose, amend, submit, drip, remit, respond, ping,
sign, claim, comment-issue, post, file-issue, immunize, bless, heart,
metronome, retro, check, leakdog.

## The audit

For each actor, find every path that produces inbox cards, fires
andons, or terminates without routing. Classify each path against
the seven violation patterns below. Skip actors with zero findings.

## Violation patterns to look for

### V1. Silent fall-through

The actor finishes work but doesn't route the card anywhere (no kick,
no event, no human-inbox deposit). Usually shows up as:
- An `if` block that handles one verdict but no `else` for other shapes
- An exception caught with `except: pass` that discards the work
- A `return` after logging but without downstream kick

The 2026-05-18 ghost-branch case was this — shipped verdict, no branch
on origin, fell through to human inbox instead of silent-ghost event.

**Search**: `git grep -n "except.*:.*pass\|return result\|return {.*skip" sweep/activities/`

**Fix shape**: every exit path either kicks a downstream card or emits
an event that names what happened. Never both silent.

### V2. Generic reason text

The inbox card's `reason` or the andon's message is a hardcoded string
that's the same for many different shapes of failure. The operator
can't tell what actually happened without opening the artifact.

The "skill's go-with-the-flow heuristic couldn't pick" case was this —
stamped on every human card regardless of why.

**Search**: `git grep -n '"reason":\|reason=' sweep/activities/ | grep -v "f\""`

**Fix shape**: the reason field is signal-specific. Per-case branches
produce per-case reasons. Or use the artifact's own summary line as
the reason.

### V3. No-remediation andon path

The activity raises ApplicationError with a generic message and no
recording of "what was the wrong assumption." Operator clears the
andon and the substrate has no record of what to refine.

**Search**: `git grep -n "raise ApplicationError" sweep/activities/`

**Fix shape**: the andon's message includes "what we expected, what
actually happened." Or the activity emits an event with the assumption
that fired before raising.

### V4. Fall-back-to-human-default

Code that routes to the human inbox as the catch-all for any
unclassified case. Without a discipline of "could policy refinement
auto-route this?" the human inbox accumulates duplicate shapes.

**Search**: `git grep -n "kick_human_decision\|human.jsonl" sweep/activities/`

**Fix shape**: before routing to human, check the case against known
policy patterns (kill list, classifier signals, retro params). If
none match, the human card carries a "this is a new shape, refine
policy after handling" flag.

### V5. Empty/error returns without explicit contract

Functions whose prompt says "empty is legal" but wrapper treats empty
as failure. Or wrappers that distinguish "transient error" from
"structural error" only via heuristic.

The `infer_test_cmd` empty-stdout case was this.

**Search**: `git grep -n "empty stdout\|returned empty\|allow_empty" sweep/`

**Fix shape**: every LLM-call wrapper has an explicit `allow_empty`
flag (or equivalent) and callers thread it correctly. The prompt's
stated contract matches the wrapper's behavior.

### V6. Repeated andon shapes

Andons that have fired more than 3 times in 30 days on the same actor
with similar `reason` text. The remediation never landed; the same
class keeps firing.

**Search**:
```
python3 -c "
import json
from collections import Counter
c = Counter()
for l in open('$HOME/.sweep/events.jsonl'):
    r = json.loads(l)
    if r.get('kind') != 'andon_recorded': continue
    key = (r.get('actor',''), (r.get('reason') or '')[:80])
    c[key] += 1
for (actor, reason), n in c.most_common(10):
    if n >= 3:
        print(f'{n:3} {actor:25} {reason}')
"
```

**Fix shape**: each recurring shape gets a memory entry naming the
assumption, or a code change retiring the failure mode.

### V7. Missing pokayoke intake

Actors that don't call their `<actor>_intake` from `sweep/pokayoke.py`
at activity entry. These actors burn LLM/subprocess time on cards
they should skip (evicted repos, closed PRs, drafts, etc.).

The 2026-05-19 triage / investigate / qa wiring closed three of these.

**Search**:
```
for actor in attest compose qa amend reqa triage investigate; do
  echo "=== $actor_intake usage ==="
  git grep -l "${actor}_intake" sweep/activities/ | head -3
done
```

**Fix shape**: every activity that does any LLM call or expensive
work starts with `skip = pokayoke.<actor>_intake(msg); if skip: ...`

## Output format

Produce a markdown table per actor, then a summary.

```markdown
## Actor: <name>  (file: sweep/activities/<file>.py)

| Path | Violation | Severity | Fix |
|------|-----------|----------|-----|
| `func_name:line` | V1 silent fall-through | high | route to <target> or emit <event> |
| ... | ... | ... | ... |
```

Severity:
- **high** — actively burns human attention (V1, V4, V6)
- **medium** — opaque or wastes work (V2, V3, V7)
- **low** — contract mismatch but not currently firing (V5)

End with:

```markdown
## Summary

- N actors audited
- N violations found (high/medium/low breakdown)
- Top 5 to fix first:
  1. ...
  2. ...
```

## Discipline

Don't fix during the audit. Just report. The operator decides which
violations to remediate first; fixing inline buries the audit findings.

For each violation, name **the assumption that should have produced a
different behavior**. That's the durable artifact that goes into a
memory or code comment after the fix.

## Reference

- `HUMAN_ATTENTION_PRINCIPLE.md` — the principle
- `~/.claude/projects/-Users-junekim-Documents-sweep/memory/feedback_four_knowledge_states.md`
  — fuller reasoning, for the LLM's context
- `~/.claude/projects/-Users-junekim-Documents-sweep/memory/feedback_signal_to_artifact.md`
  — operationalizes "every signal produces a durable artifact"
