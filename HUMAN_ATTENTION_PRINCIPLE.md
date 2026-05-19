# The human-attention principle

The substrate has finite human attention. Every inbox card and every
andon-cord moment is a withdrawal from that account. The principle:
**human attention must produce a durable change.** If a card just gets
acked or an andon just gets cleared without moving the substrate's
knowledge forward, that attention was wasted — and worse, the same
case will surface again, compounding the waste.

The frontier of substrate knowledge has four states. Every withdrawal
of human attention should move a case across this frontier toward
known-known.

## The four states

```
                  unknown          known
                ┌──────────────┬──────────────────┐
       wrong    │ unknown-     │ FALSE-KNOWN      │
                │ unknown      │ (andon)          │
                │ (silent      │ — was confidently│
                │  failure)    │   handled, was   │
                │              │   wrong          │
                ├──────────────┼──────────────────┤
       right    │              │ KNOWN-UNKNOWN    │
                │              │ (inbox)          │
                │              │ — ambiguous,     │
                │              │   defer for      │
                │              │   disambig +     │
                │              │   policy refine  │
                └──────────────┴──────────────────┘
```

## The frontier moves

```
unknown-unknown ──────────► known-unknown ──────────► known-known
   (silent fail)              (inbox card)             (handled)
                                                          │
                                                          │ assumption
                                                          ▼ wrong
                                                      false-known
                                                       (andon)
                                                          │
                                                          │ remediated
                                                          ▼
                                                       known-known
```

Unidirectional toward known-known. Every action should move a case
forward, or surface a previously-hidden frontier.

## What good looks like

**Human inbox card** — ideal outcome:
- The case is **disambiguated** by operator decision
- The policy is **refined** so the next instance of this case doesn't
  reach inbox
- Durable artifact lands: classifier widening, memory entry, contract
  update, or code change

**Andon-cord moment** — ideal outcome:
- The previously-wrong **assumption is named** (in a memory entry or
  code comment: "what we thought" + "what it actually is")
- The substrate's confidence is **corrected** so the class of error
  won't recur
- Durable artifact lands as above

## What junk looks like

**Bad inbox card** (point at this doc when you see one):
- Repeats the same shape another card already raised — policy never
  got refined from the prior one
- Generic reason like "operator must decide" with no actionable
  disambiguation context
- Could have been auto-routed if the classifier knew one more pattern
- Operator's decision wouldn't change anything structural

**Bad andon** (point at this doc when you see one):
- Same andon repeats after being cleared — remediation never landed
- The reason is "Activity task failed" with no underlying assumption named
- Just clearing it without recording what was wrong
- The class of failure isn't documented anywhere afterwards

## How to use this

When you encounter a card or andon that smells like junk:

1. Quote this doc.
2. Identify which state-transition the substrate failed to make.
3. Demand the durable artifact:
   - For inbox: "what policy refinement would make the next instance
     of this auto-route?"
   - For andon: "what assumption was wrong, and where is that
     correction recorded?"

If neither has an answer, the substrate is producing entropy without
moving the frontier. Fix the upstream code path, not the symptom.

## Why this matters

The substrate's growth is the frontier moving from unknown-unknown
toward known-known. Without discipline at the inbox and andon
boundaries, the substrate accumulates the same cases over and over
without learning — operator attention burns, frontier doesn't advance,
the same surprises repeat.

The asymmetry: silent failure is **strictly worse** than inbox card,
which is strictly worse than known-known. Every fix should move a case
upward, never the other way (e.g., don't add a "default to most common
path" for an edge case — defer to inbox instead).

## Examples from 2026-05-18 session

Each was a false-known that fired an andon (or worse, silently dropped):

| Symptom | False assumption | Correction |
|---|---|---|
| Investigations missing from inbox | "we route human-gated to human inbox" | Path-import bug; missing import |
| Tissue drafts silently lost | "skill produces fenced output" | Bug + instrumentation |
| Cockpit blank despite throughput | "acked = drop is safe" | broom keep-all |
| $100/day auto-recharges | "OAuth wins over API key by default" | Centralized env-pop |
| Classifier missing real ships | "regex patterns suffice" | switch actor (LLM) |
| Empty stdout = activity error | "claude returning empty means broken" | `allow_empty` flag (prompt said empty was legal) |
| Shipped → human inbox | "shipped always routes to qa" | silent-ghost for branchless |

All of these were avoidable if the substrate had asked "what's the
assumption?" at each confident handling point.

## See also

- `feedback_four_knowledge_states.md` in the substrate's memory — full
  reasoning, for the LLM's reference
- `feedback_signal_to_artifact.md` — every signal produces a durable
  artifact (this doc is the operationalization)
- `feedback_done_visibility.md`, `feedback_dry_mode_outbound_only.md`,
  `feedback_claude_cli_prefers_api_key.md` — examples of the false-known
  shape getting plugged
