# Retro Graph: antonmedv/fx

Author: kimjune01 | Period: May 9 2026 (pre-registration) | Record: 0/0 (no submissions yet)

## Own outcomes

None. This is a pre-registration document.

## Prior art

| # | Author | +/- | Result | Time to merge | Note |
|---|--------|-----|--------|---------------|------|
| 412 | dkarter | +1/-1 | **MERGED** | 42 min | CVE bump, trivial |
| 411 | mmoskal | +21/-1 | **MERGED** | 11 hours | JSON escape fix, functional |
| 406 | umut-polat | +6/-5 | **MERGED** | 1.5 hours | Config path fix |
| 395 | groutoutlook | +1/-1 | **MERGED** | 3.9 hours | Editor line number |
| 358 | EstebanDem | +7/-1 | **MERGED** | 5.4 hours | Yank key+value |
| 355 | chojs23 | +833/-3 | **MERGED** | 1.2 hours | Search caching |

**Merged external ratio:** 7/10 recent merges are external contributors. Solo maintainer (antonmedv) merges quickly when PRs fit his vision.

**Rejection pattern -- AI detection is a kill switch:**

| # | Author | +/- | Result | Quote |
|---|--------|-----|--------|-------|
| 387 | giskard-prime-5906 | +221/-1 | Closed | "Claude code PR without author reviewing the code. Closing." |
| 378 | xingarr | +385/-225 | Closed | "Is it AI generated?" -> "Looks like you didn't even try to build" |
| 393 | LMKKK | +428/-0 | Closed | "I'm working on integrated interactive query" (scope conflict) |

antonmedv explicitly checks for AI authorship. #387 closed solely on AI suspicion (username "giskard-prime" is a tell). #378 closed after AI probe + build failure. Both had functional code.

## Hypothesis evidence

**H2: Standing gates quality** -- STRONG FOR. antonmedv merges 1-line CVE bumps from unknowns (dkarter) but rejects 221-line features from AI-suspected accounts. The gate is not code quality -- it's author credibility. Solo maintainer = sole gatekeeper = standing is everything.

**H5: Review efficiency over correctness** -- STRONG FOR. Median time-to-merge for external PRs: ~2 hours. antonmedv reviews fast, decides on pattern fit, not committee process. #393 rejected because it overlapped his own roadmap ("I'm working on integrated interactive query"), not because the code was wrong.

**H4: Framing affects outcome** -- FOR. #387 was functional code, closed on framing alone ("Claude code PR"). The username was the evidence, not the diff.

**H3: Drip pacing** -- UNDETERMINED. Fast review cycle (~2 hours) means pacing matters less than standing. But flooding from a single unknown could trigger the AI detector.

## Pre-registration

| Target | Fix | Lines | Schema |
|--------|-----|-------|--------|
| #408 | Custom string preview transform | ~80 | Issue-first, feature request from maintainer |

**Prediction (H5):** Merge if: (1) implementation matches antonmedv's mental model of the feature, (2) no overlap with his in-progress work, (3) human voice in PR description. Reject if: PR reads as AI-generated, or scope conflicts with his "integrated interactive query" plans (see #393).

**Falsification:** H2 falsified if a well-framed 80-line PR from a zero-standing account merges without any standing-building preamble. H5 falsified if antonmedv requests multi-round review instead of quick accept/reject.
