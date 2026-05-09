# Retro Graph: Aider-AI/aider (kimjune01)

**Date:** 2026-05-08
**Window:** 2 PRs, May 2026

## Own Outcomes

| # | Title | +/- | State | Hypothesis | Reviewer signal |
|---|-------|-----|-------|------------|-----------------|
| 4941 | Add /topics and /drop-topic commands | +2465/-4 | CLOSED | H6 (silent rejection) | Zero response from paul-gauthier. Self-closed after ping. |
| 4940 | Add opt-in union-find chat history summarizer | +1997/-4 | CLOSED | H6 (silent rejection) | Zero response. Self-closed after ping. |

## Hypothesis Classification

**H0 (null):** 0 cases.
**H1 (lands):** 0 cases.
**H2 (scope mismatch):** Possible contributing factor -- both PRs were 2000+ lines of new feature code. But the primary signal is silence, not scope feedback.
**H3 (crowded out):** 0 -- no competing PRs.
**H4 (style/convention):** 0 -- no style feedback given.
**H5 (policy gate):** 0 -- no policy cited.
**H6 (maintainer bottleneck / silent rejection):** Both cases. paul-gauthier is effectively the sole reviewer and did not engage at all. No comment, no label, no close. Pure silence.

## Prior Art

paul-gauthier merges external PRs regularly -- but only small ones:

| Author | Example | Size |
|--------|---------|------|
| claui | #4935 (deprecated models) | +2/-5 |
| chr15m | #4830, #4682, #4674 | 5-9 lines |
| codeofdusk | #4698, #4656 (model adds) | config-only |
| markmcd | #4772 (remove dep) | +130/-155 net-negative |

**Base rate:** External merges are under 200 lines, typically under 50. Bug fixes, config, or removals. No external feature PR over 200 lines in recent history.

**Diagnosis:** Both closed PRs (+2465, +1997) were 10-50x the merge ceiling. Silence is the size filter.

## Pre-registration

### #3702: --no-verify-ssl fails for gemini/openrouter (issue, priority label)

**Fix:** 2 lines production (`SSL_VERIFY = "False"` + `litellm.ssl_verify = False`).

**Prediction:** 75% merge probability. Matches every signal that predicts success in this repo:
- paul-gauthier labeled it "priority" (he wants it fixed)
- 2-line production change (well under the ~50-line merge ceiling)
- Existing test coverage for this path
- Bug, not feature

**Risk:** diverdale posted a root-cause analysis on Apr 30. Check for competing PRs before submitting. If someone else already has a PR open, this becomes H3 (crowded out).

**Expected hypothesis if merged:** H1 (small fix lands).
**Expected hypothesis if rejected:** H4 (style -- paul-gauthier prefers a different fix approach) or H3 (scooped).

## Lessons

1. **paul-gauthier merges small, ignores large.** The merge ceiling for external contributors is ~200 lines. Both submitted PRs were 10x over.
2. **Silence is the rejection signal.** No comments, no close, no labels. The absence of engagement is the data.
3. **Align with labeled issues.** The only viable path is fixing bugs the maintainer already wants fixed. #3702 (priority label) is the template.
4. **Do not submit unsolicited features.** Without prior discussion or issue alignment, large feature PRs are dead on arrival.

---

*Retro -- backward pass from outcomes to hypotheses.*
