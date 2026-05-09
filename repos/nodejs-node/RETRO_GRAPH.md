# RETRO_GRAPH: nodejs/node

## Prior Art (last 15 merged PRs)

Core team dominates: aduh95 (4), RafaelGSS (3), panva (2), ljharb (1), jasnell (1) — 11/15 from collaborators with commit access.

External contributors merged: geeksilva97 (+27/-1 doc), mertcanaltin (+2/-4 cleanup), Renegade334 (+63/-47 stream edits), Anshikakalpana (+16/-0 doc deprecation). Rate: **4/15** (27%).

First-timers fare well on doc/deprecation PRs. Anshikakalpana got #63121 (doc-only HMAC deprecation) merged, then opened #63162 (runtime deprecation) — still open.

## Pre-registration

**HMAC deprecation (DEP0206)** — two-phase approach visible:
1. #63121 (doc-only deprecation): **MERGED**. Anshikakalpana, +16/-0.
2. #63162 (runtime deprecation): **OPEN**. Anshikakalpana, +37/-1. This is the competing PR.

Our angle was #62838 (not found — may be an issue number or was closed/renumbered). **BLOCKED** by #63162 which covers the same runtime deprecation. If #63162 stalls or gets rejected, the path reopens.

## Meta-hypotheses

| ID | Hypothesis | Evidence | Classification |
|----|-----------|----------|----------------|
| H0 | Core team merges external PRs | 4/15 external merged | Confirmed but low rate |
| H1 | Doc/deprecation PRs are first-timer friendly | Anshikakalpana doc merged quickly | **Confirmed** |
| H2 | Runtime deprecation PRs need collaborator sponsor | #63162 still open, doc merged fast | Likely — higher bar for runtime changes |
| H3 | Competing PRs kill late arrivals | #63162 occupies the HMAC slot | **Active risk** |

## Base rates

- External merge rate: 27% (low — gated by collaborator review)
- Doc-only PRs: fast merge, low bar
- Runtime behavior changes: slower, needs CI + collaborator approval
- Competing PR resolution: unpredictable

## Risk

High. #63162 covers our target deprecation. Unless it stalls (no activity for 2+ weeks), attempting the same change invites "duplicate" closure. Monitor #63162 weekly. If it stalls past 4 weeks, open a clean alternative with a ping to the original author.
