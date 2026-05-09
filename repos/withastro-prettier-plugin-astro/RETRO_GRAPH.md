# RETRO_GRAPH: withastro/prettier-plugin-astro

## Own Outcomes

None yet. No PRs opened.

## Prior Art: External Contributors

| PR | Author | +/- | Wait | Outcome |
|---|---|---|---|---|
| #448 | nylexar-sudo | +49/-2 | 24d | Merged |
| #447 | nylexar-sudo | +33/-2 | 24d | Merged |
| #441 | denbezrukov | +137/-18 | 16d | Merged |
| #417 | cstrlcs | +41/-0 | 8d | Merged (feature) |
| #413 | ryanleichty | +1/-1 | 128d | Merged (README typo, low priority) |
| #455 | kitschpatrol | +?/-? | <1d | Closed, no review, no changeset |

**Pattern:** External PRs merge in 1-4 weeks. The repo moves slower than compiler (fewer maintainers active, lower commit frequency). Last non-bot merge was Oct 2025 -- 7 months ago. nylexar-sudo is the most recent external contributor with substantive merges. #455 was closed same-day with no review (no changeset, possibly incomplete).

**Key risk:** This repo is low-activity. PRs may wait longer simply because maintainers check it less often. Pinging is more important here than in compiler.

## Cross-Repo Maintainer Overlap

Princesseuh maintains both compiler and prettier-plugin-astro. Review bandwidth is shared. When compiler has a burst of activity (like the Apr 27 merge batch), prettier-plugin may get starved. Coordinate timing: don't open PRs in both repos the same week.

## Meta-Hypotheses

- **H0 (null):** REJECTED. Same pattern as compiler -- external PRs wait weeks.
- **H2 (changeset):** SUPPORTED. #455 (no changeset) closed; #447-448 (with changesets) merged.
- **H3 (ping cadence):** UNTESTED here but predicted to matter more given low activity.
- **H5 (bandwidth):** STRONGLY SUPPORTED. 7 months since last substantive merge. Maintainer attention is episodic.
- **H6 (reputation):** WEAK. nylexar-sudo was unknown and still merged in 24d. Repo may be less gatekept than compiler.

## Pre-Registration

**#308 — formatter adds significant whitespace inside expressions**
- Size: medium-high. JSX/HTML whitespace handling is architecturally sensitive.
- Princesseuh confirmed the bug (12 comments on issue, active discussion).
- Prediction: 3-6 weeks to merge if PR is clean, has changeset, and includes test cases. Risk of scope creep -- the issue has 12 comments showing disagreement on correct behavior. Pin the fix to one specific case, don't try to solve the general whitespace problem.
- Timing: Open after compiler #1162 merges. Don't compete for Princesseuh's attention.
