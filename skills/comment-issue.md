---
name: tissue
description: Side-hatch — when an investigation concludes "no fix to ship" but produced real diagnostic value, draft a one-paragraph comment that reports findings back to the maintainer. Polite, evidence-grounded, deferential. The operator approves before posting.
argument-hint: <owner/repo>#<issue>
allowed-tools: Read, Bash
---

# Tissue: a tissue for your issue

> Maintainer files an issue. Pipeline notices something useful (already-fixed-upstream, premise-killed, stale). Side-hatch offers a tissue — a small kindness, polite gesture, no obligation. Easy to accept, easy to ignore. The whole posture is: "thought you might want this; carry on."

The pipeline's primary exit is a PR. The side hatch is information — when investigation concludes there's nothing to ship (already-fixed-upstream, stale, premise-killed, policy-gated), the analysis itself has value for the maintainer. This skill drafts that report.

You were invoked on one issue with a completed hypothesis graph at `repo-hypotheses/<owner>__<repo>__<issue>.md`. Read it, find the load-bearing evidence, draft one paragraph.

## What lives in the artifact

The hypothesis graph has the structure: H₀..Hₙ (hypotheses), perturbations + results, halt section with verdict. The halt section is the load-bearing claim. The body has the evidence (linked upstream PRs, commit hashes, file refs, repro confirmations).

## What the comment must do

| Requirement | Why |
|---|---|
| **Lead with the finding** | One sentence stating the conclusion. No preamble, no "thanks for the report." |
| **Cite evidence** | Link the upstream PR / file / commit / line that grounds the claim. The maintainer should be able to verify in one click. |
| **Defer to maintainer** | Close with "you may want to close" or "let me know if I've misread." Never tell them what to do. |
| **Stay under 120 words** | Each extra sentence is a tax on attention. Maintainers skim. |
| **One paragraph** | No bullet lists, no headings. Reads like a polite peer comment, not a bot report. |

## What the comment must NOT do

- **Apologize or be effusive.** "Sorry to chime in," "great issue!" — both are noise. Just report.
- **Advise on the fix.** If a fix would still help, that belongs in a PR (separate path). The side-hatch comment is information, not direction.
- **Cite the hypothesis-graph file or sweep internals.** The maintainer doesn't care about our pipeline's structure; they care about the finding.
- **Speculate.** If the artifact doesn't ground a claim, don't make it. Better to draft a shorter comment than a confident wrong one.
- **Pretend uncertainty doesn't exist.** If the artifact's verdict is "looks resolved" rather than "is resolved," the comment must reflect that hedge.

## Output shape

Print the drafted comment as the **last** lines of stdout, fenced like this so the wrapper can parse it:

```
<<<COMMENT
Looking into this — the symptom appears to be resolved by [#1820](link), which landed in 11f8662c and matches the failure mode reported here. You may want to close.
COMMENT>>>
```

Anything before the fence is for your own reasoning trace — the wrapper only extracts what's between the fences.

If after reading the artifact you conclude there's no value in a comment (vague verdict, no evidence, would be noise), output:

```
<<<COMMENT
SKIP: <one-line reason>
COMMENT>>>
```

The wrapper treats SKIP as "discard this card." Better to skip than to post a thin comment that taxes the maintainer's inbox.

## Example

Input: `pingcap/tiflow#12636`. Artifact says: "Badge pointed to a deleted workflow; fix is a one-line README delete already in flight by the reporter."

Good draft:
> Looking into this — the broken badge points to a workflow that was removed; the reporter (@dveeden) has already opened #12638 with the README fix. Feel free to close this once that lands.

Bad draft (apologetic, citing nothing):
> Hi! Sorry to chime in. I noticed this issue looks like it might already be fixed. You should probably close it, but feel free to keep it open if you want.

The good one earns 1 second of maintainer attention and either gets a reaction or quietly closes the loop. The bad one earns a mute.
