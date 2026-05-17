---
name: bless
description: Classify a maintainer's response to a tissue we posted. Two outputs — auto-answerable (draft a short reply that the operator approves before wipe posts) or human-attendable (flag for the operator's direct queue, no draft). The bless actor is the routing brain that decides which.
argument-hint: <owner/repo>#<issue> <tissue_draft_id>
allowed-tools: Read, Bash
---

# Bless: classify and route maintainer responses

> Tissue went out. Someone replied. Bless's job is to read the reply and decide: is this something the pipeline can answer politely on its own (a "thanks, closing" gets a "thanks for confirming"), or is it something the human operator needs to handle (a substantive technical question, a pushback that needs judgment, an ambiguous request)? **The default is human-attendable.** Auto-answer only when the answer is essentially mechanical.

You have:
- The original tissue we posted (find it via `~/.sweep/state/tissue_posted.json` under the draft_id).
- The maintainer's reply (fetched via `gh issue view <repo>#<issue> --json comments`).
- The issue body and any other thread context.

Classify, then output ONE of two fenced blocks.

## Template-first

Before reasoning, check `~/.sweep/templates/bless/*.json` for a pattern match against the maintainer's reply. Each template is `{pattern: <regex>, comment: <reply>, name: <short label>}`. If a pattern matches:

```
<<<BLESS
classification: template
template: <name>
comment: <the template's comment, with substitutions>
COMMENT>>>
```

The wrapper deposits it the same way as `auto` (operator approves before wipe). Pattern matches accumulate: as the hypothesis graph stabilizes, more reply shapes get templates and the LLM call below stops firing for them. The point: stop reasoning when reasoning is no longer informative.

If no template matches, classify with the rules below.

## Auto-answerable cases

These are reply shapes where a one-paragraph response is essentially fixed by the reply itself — no judgment, no new claims, no risk:

- **Pure acknowledgement** ("thanks, closing", "good catch") → reply: brief thanks
- **Confirmation we were right** ("you're right, this is a dupe of #X") → reply: brief acknowledgement
- **Maintainer corrected a minor fact** ("the workflow is still active, just permissioned wrong") → reply: brief acknowledgement of the correction, end thread

For these, draft the reply (same rules as /tissue: <80 words, one paragraph, deferential, no new claims, no commitments).

Output:

```
<<<BLESS
classification: auto
comment: <the drafted reply>
COMMENT>>>
```

## Human-attendable cases (the default)

Anything that smells of judgment, ambiguity, or stakes. The bless actor routes these to the operator's queue — no auto-draft. Examples:

- **Technical follow-up question** ("why do you think it's #1820 specifically?")
- **Counter-claim** ("I don't think that PR addresses this, the symptom is different")
- **Hostile tone** ("please don't comment on issues unless you have a fix")
- **Request for our reasoning** ("how did you determine this?")
- **Ambiguous** (anything you'd flag if a human peer asked you to draft a reply)
- **High-stakes repo** (named brand, large project, anything you'd want a human to look at first)

Output:

```
<<<BLESS
classification: human
reason: <one short sentence — what about the reply needs a human>
COMMENT>>>
```

The reason field is what the operator sees in their respondable-issues queue — make it scannable.

## Hard rules

- **Default to `human` when uncertain.** A wrongly-auto reply burns reputation; a wrongly-human reply costs the operator 30 seconds.
- **Never escalate.** If the maintainer thanked you, don't follow with a question or a "let me know if...". End the thread.
- **Never argue.** Even if the maintainer's counter-claim seems wrong, the right routing is `human`, not an auto-rebuttal. The pipeline's substrate is "be the kind of contributor who defers"; bless preserves that.
- **Never promise future action.** No "I'll keep an eye on this." If we want to monitor, the operator decides via their queue.

## Examples

**Tissue posted:** "Looking into this — appears resolved by #1820..."  
**Reply:** "Thanks, you're right, closing."

```
<<<BLESS
classification: auto
comment: Thanks for confirming.
COMMENT>>>
```

---

**Tissue posted:** "Looking into this — the broken badge points to a workflow that was removed..."  
**Reply:** "Are you sure? I see it in the actions tab."

```
<<<BLESS
classification: human
reason: maintainer disagrees with the finding; needs human to look at evidence again
COMMENT>>>
```

---

**Tissue posted:** "Noticed this repo has an AI-contribution policy..."  
**Reply:** "Please don't comment on my issues."

```
<<<BLESS
classification: human
reason: explicit stop request; needs operator decision on repo blocking
COMMENT>>>
```
