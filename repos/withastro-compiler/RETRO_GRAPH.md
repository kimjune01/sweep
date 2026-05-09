# RETRO_GRAPH: withastro/compiler

## Own Outcomes

**#1162 — strip dead imports for client:only** | OPEN
+246 -6, changeset added, 0 reviews, 0 maintainer comments.
Open 2 days, no engagement yet. Score: 9/10 actionability.
Classification: PENDING. Too early to classify against H0-H6.

## Prior Art: External Contributors

| PR | Author | +/- | Wait | Outcome |
|---|---|---|---|---|
| #1156 | seroperson | +147/-24 | 39d (3 pings) | Merged, "apologies for delay" |
| #1151 | meyer | +468/-13 | 58d (0 pings) | Merged, no maintainer comment until merge day |
| #1149 | martrapp | +57/-1 | same day | Merged (known contributor) |
| #1123 | ocavue | +7/-0 | 3d | Closed, no review |
| #1108 | jp-knj | +refactor | 6mo | Closed by maintainer cleanup |

**Pattern:** External PRs wait 3-8 weeks unless author is a known collaborator. Pinging accelerates but doesn't guarantee speed. Small refactors get closed without review. Feature PRs with tests and changesets eventually merge. Princesseuh is the gatekeeper; matthewp reviews less frequently.

**Rejection signal:** #1123 closed in 3 days with no review = scope disagreement. #1108 closed after 6 months = abandoned/stale cleanup.

## Meta-Hypotheses

- **H0 (null):** External PRs merge at the same rate as internal. REJECTED. Internal PRs merge same-day; external wait weeks.
- **H1 (size):** Smaller PRs merge faster. WEAK SUPPORT. #1149 (small, same-day) vs #1151 (large, 58d). But #1123 (small) was rejected.
- **H2 (changeset):** PRs with changesets merge; without get closed. SUPPORTED. #1162 has one. #1123 lacked one and was closed.
- **H3 (ping cadence):** Pinging every 1-2 weeks keeps PRs alive. SUPPORTED. seroperson pinged 3x across 39d, got merged. meyer never pinged, waited 58d.
- **H4 (issue-linked):** PRs closing known issues get priority. UNTESTED for our PRs yet.
- **H5 (maintainer bandwidth):** Merges cluster around release events. SUPPORTED. #1151 and #1156 both merged on Apr 27 (same batch).
- **H6 (reputation):** First-time contributors wait longer. SUPPORTED. martrapp (known) = same day; seroperson (new) = 39d.

## Pre-Registrations

| Issue | Size | Prediction |
|---|---|---|
| #1091 (backslash) | ~2 lines | Merge in 2-4 weeks if changeset included. Maintainer pointer exists (MoustaphaDev comment). |
| #1139 (Astro.self) | 10-15 lines | 4-6 weeks. Server islands = active area, but no maintainer comment on issue. |
| #1096 (slot order) | 2-5 lines | 2-3 weeks. Small, clear bug, low risk. |
| #1116 (table DOM) | medium | 3-5 weeks. Closes 3 issues = high value but higher review burden. |
| #1068 (whitespace) | ~20 lines | 4-8 weeks. Overlaps with meyer's #1151 (whitespace area). Potential conflict. |

**Prediction for #1162:** First review in 1-3 weeks. If Princesseuh approves, merge within 1 week of review. Ping at day 7 if no response.
