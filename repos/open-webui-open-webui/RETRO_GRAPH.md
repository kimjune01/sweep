# Retro Graph: open-webui/open-webui

Author: kimjune01 | Period: May 9 2026 (pre-registration) | Record: 0/0 (no submissions yet)

## Own outcomes

None. This is a pre-registration document.

## Prior art

| # | Author | +/- | Result | Time to merge | Note |
|---|--------|-----|--------|---------------|------|
| 24468 | Classic298 | +5/-3 | **MERGED** | 2 min | DOMPurify, trusted contributor |
| 24461 | Classic298 | +78/-24 | **MERGED** | 33 min | Stream fix, OOM prevention |
| 24384 | jmleksan | +7/-0 | **MERGED** | 3.1 days | Probe endpoint fix |
| 24380 | jmleksan | +10/-2 | **MERGED** | 3.2 days | DB ping offload |
| 24379 | jmleksan | +7/-1 | **MERGED** | 3.2 days | STT offload |
| 24370 | Classic298 | +10/-1 | **MERGED** | 3.5 days | URL validation |

**Contributor concentration:** 6/10 recent merges from Classic298, 3/10 from jmleksan. Tight inner circle. tjbck (maintainer) handles release PRs. ~30 open PRs at any time with issue numbers reaching 24k+.

**Rejection pattern -- low-effort flood:**

| # | Author | Note |
|---|--------|------|
| 24476, 24474, 24473 | pedroyob | "Develop" / "Iades custom core" -- fork pushes, closed instantly |
| 24427 | mfidosjr | "docs: adiciona pasta de reengenharia" -- Portuguese docs dump |
| 24426 | cadeferg | "Medical guardrails" -- 510 lines, unsolicited feature |

High-volume repo attracts drive-by PRs. Maintainer closes junk fast. Signal-to-noise ratio is the core challenge.

## Hypothesis evidence

**H4: Framing affects outcome** -- UNDETERMINED (this is the testbed). open-webui describes itself as AI-friendly. But the merge pattern shows insider dominance: Classic298 and jmleksan account for 9/10 merges. "AI-friendly" policy may not translate to outsider acceptance.

**H2: Standing gates quality** -- FOR. Classic298 merges in 2 minutes. jmleksan in ~3 days. Unknown contributors' PRs sit in the 30-PR backlog or get closed as noise. Standing stratification is steep.

**H5: Review efficiency** -- FOR. tjbck batches merges (3+ PRs merged same day), suggesting review sessions rather than per-PR engagement. PRs that don't fit a session get deferred indefinitely.

**H3: Drip pacing** -- UNDETERMINED. High volume means any single contributor's drip is noise. The question is whether a well-framed PR from an unknown can even get seen.

## Pre-registration

| Target | Fix | Lines | Schema |
|--------|-----|-------|--------|
| #2790 | aria-labels for accessibility | ~15 | Issue-first (linked to #277), a11y improvement |

**Prediction (H4):** This is the key H4 test. AI-friendly policy says disclosure shouldn't hurt. But with 24k+ issues and insider-dominated merges, the real gate is attention, not policy. Predict: merge takes >7 days even for a 15-line a11y fix, because outsider PRs queue behind trusted contributors. AI-disclosure neither helps nor hurts -- supply flood is the dominant factor.

**Falsification:** H4 falsified if AI-disclosed PR merges faster than the 3-day insider baseline (jmleksan's rate). H4 confirmed if merge takes >7 days or gets lost in backlog despite being a clean 15-line a11y fix. H2 falsified if the PR merges in <24 hours without any prior standing-building.
