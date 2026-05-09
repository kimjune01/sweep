# Retro Graph: tinygrad/tinygrad

Author: kimjune01 | Period: May 7--9 2026 | Record: 1/14 merged (7%)

## Own outcomes

| # | Title | +/- | Result | Reviewer verbatim |
|---|-------|-----|--------|-------------------|
| 16085 | onnx: dedup proto parsers | -62/+22 | **MERGED** | geohot: "Cool! Wow that old code never should have been merged" |
| 16117 | PTX test and fix | +11/-1 | Closed | Qazalin: "that test passes in master too. write a failing test and fix the root cause" |
| 16116 | MATVEC test and fix | +12/-1 | Closed | geohot: "Last warning about low quality PRs before I ban you" |
| 16113 | Failing tests | +23/-0 | Closed | geohot: "A PR means I have spent serious human time reading this and 100% believe you are ready to just click merge" |
| 16111 | fix MATVEC pattern | +1/-1 | Closed | geohot: "I'm not reading anything written by AI" |
| 16108 | fix is_dtype_supported | +4/-1 | Closed | geohot: "I don't understand what this does. There's no regression tests" |
| 16107 | post-TC heuristic | +8/-11 | Closed | geohot: "no on all heuristic changes until we have way more comprehensive validation" |
| 16096 | skip redundant UPat root check | +73/-7 | Closed | geohot: "You need to stop with AI PRs, you will be banned. We never trade complexity for speed" |
| 16072 | MV_ROWS_PER_THREAD 4->16 | +3/-3 | Closed | geohot: "tuning this stuff is really annoying. We don't have a good way to test it on many different devices" |
| 16070 | add Ops.WARP_REDUCE | +52/-3 | Closed | geohot: "we never trade complexity for speed" |
| 16109, 16104, 16094, 16069 | (self-closed / no review) | -- | Closed | -- |

## Prior art

| # | Author | Result | Quote |
|---|--------|--------|-------|
| 15401 | geohot | **MERGED** | (self-labeled "ai slop flash attention (it works)") |
| 15591, 15166, 15080 | geohot | Closed | (self-labeled "AI slop", self-closed when unready) |
| 15553 | Patrickeik | Closed | geohot: "This is AI slop, we should just close" |
| 15491 | Sou-ly | Closed | geohot: "DO NOT SUBMIT AI SLOP" |

## Hypothesis evidence

**H0: Issue-first merges higher than unsolicited** -- UNDETERMINED. 0/14 were issue-first. The merge (16085) was unsolicited but addressed obvious dead code. Pre-registered issues (12296, 6909, 13179, 11908) ship May 22.

**H1: Review schema conformance predicts merge** -- FOR. The merge (net -40 lines) met every criterion: no complexity, clear value, tests pass. Every rejection violated at least one: no regression test (16108, 16117), complexity-for-speed (16096, 16070), heuristic tuning without device CI (16107, 16072). Implicit schema: net-negative lines, regression test, no complexity tradeoff.

**H2: Standing gates technical quality** -- STRONG FOR. geohot labels contributor AI slop as bannable (15553, 15491) while merging his own (15401). Standing determines whether code is evaluated or discarded. Mine degraded from neutral to near-ban across 13 rejections in 48 hours.

**H3: Drip pacing prevents standing damage** -- STRONG FOR (contrapositive). 13 PRs in 48h triggered escalating hostility: "don't understand" -> "close to banned" -> "Last warning." Flooding destroyed standing. Drip was not used.

**H4: Framing affects outcome independent of code** -- FOR. 16111 (+1/-1, genuine fix) dismissed because its description read as AI: "I'm not reading anything written by AI." Trivial code; framing killed it.

**H5: Maintainers optimize for review efficiency** -- STRONG FOR. "A PR means I have spent serious human time" (16113). Cost function is reviewer-minutes. Drafts, partials, and test-only PRs waste budget. The merge (16085) required zero back-and-forth.

**H6: Pipeline beats ad-hoc** -- UNDETERMINED. This burst was fully ad-hoc. Pipeline skills not engaged. May 22 is the first pipeline-governed submission. Baseline: 7%.

## Pre-registrations (May 22)

| Issue | Fix | Lines | Schema |
|-------|-----|-------|--------|
| #12296 | max backward underflow | net-zero | Issue-first, regression test |
| #6909 | bf16 autocast | +4 | Issue-first (open since 2024) |
| #13179 | Variable expression equality | +1 | Issue-first, regression test |
| #11908 | Beam cache invalidation | +8 | Issue-first, regression test |

**Prediction:** 3/4 merge if drip-paced (1 per 48h), own voice. 0/4 if batch-submitted.
