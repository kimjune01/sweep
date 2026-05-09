# Retro Graph: google-gemini/gemini-cli (kimjune01)

**Date:** 2026-05-08
**Window:** 7 PRs, April 2026 -- present

## Own Outcomes

| # | Title | +/- | State | Hypothesis | Reviewer signal |
|---|-------|-----|-------|------------|-----------------|
| 23341 | fix: decode Uint8Array/UTF-8 in API errors | +111/-6 | MERGED | H1 (small fix) | Bot review only, merged on quality |
| 23347 | fix: synchronous stderr before exit | +17/-18 | CLOSED | H3 (crowded out) | "address gemini comments, make tests pass" -- scooped by another contributor |
| 23343 | fix: vim escape during streaming | +43/-0 | CLOSED | H1 (already fixed) | "issue was already fixed" -- spencer426 |
| 23066 | fix: token accounting + temp file leak | +57/-17 | CLOSED | H5 (policy gate) | Closed by contribution policy update |
| 13844 | Add context window progress indicator | +764/-163 | CLOSED | H2 (scope) | "feature is already implemented" -- jackwotherspoon. Settings toggle existed. |
| 13789 | feat: deliberate context compaction | +12805/-191 | CLOSED | H5 (policy gate) | "closing to triage more recent PRs" -- bdmorgan |
| 24736 | feat: union-find context compaction | +2805/-17 | OPEN | H2 + H6 | Community LGTM, waiting on maintainer. "needs rebase," refactor to ContextProcessor. |

## Hypothesis Classification

**H0 (null):** 0 cases.
**H1 (lands):** 1 merged (#23341). 1 closed-already-fixed (#23343).
**H2 (scope):** #13844 duplicated existing feature. #24736 large, under negotiation.
**H3 (crowded out):** #23347 -- another contributor took the fix.
**H4 (style):** 0 cases.
**H5 (policy gate):** #23066 and #13789 bulk-closed by contribution policy update, not technical merit.
**H6 (maintainer bottleneck):** #24736 has community LGTM but no maintainer engaged. "Letting maintainers with powers chime in."

## Prior Art

- Googler-authored merges dominate (sripasg, cocosheng-g, adamfweidman, joshualitt).
- External merges exist but are small fixes under 100 lines (danielweis, ramgeart, devr0306).
- A contribution policy update bulk-closed older external PRs regardless of quality.
- **Base rate:** small fixes merge; large features stall or get policy-closed.

## Pre-registrations

### #25459: Shell tool UI jank

**Prediction:** ixchio already has PR #25643 open (+29/-5). Competing = H3. **Do not submit.** Monitor.

### #25693 / #25689: Good-first-issue bugs

**Prediction:** >70% merge. Small, labeled, maintainer-blessed. Drip one at a time. Expected: H1.

### #24736: Union-find compaction (open)

**Prediction:** 40% merge. ContextProcessor refactor is the gate. Complete refactor, one ping, wait. If maintainer never engages: H5/H6.

## Lessons

1. **Small fixes merge. Large features don't.** Only merge was +111/-6. Everything over 100 lines closed.
2. **Policy gates are exogenous.** Two PRs bulk-closed by policy change, not technical review.
3. **Check for existing solutions first.** #13844 and #23343 duplicated existing functionality.
4. **Maintainer bottleneck.** Community LGTMs don't merge. Google-internal reviewers control the queue.

---

*Retro -- backward pass from outcomes to hypotheses.*
