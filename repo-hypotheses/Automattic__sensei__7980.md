# Automattic/sensei#7980 — YouTube "Complete Lesson" misses near-end completion

**Issue:** [#7980](https://github.com/Automattic/sensei/issues/7980) — YouTube videos sometimes stop ~1 s before the end without firing `YT.PlayerState.ENDED`, so the Required-video gate on the Complete Lesson button never lifts.

**Status:** diagnosed, fix implemented and locally validated, awaiting Phase 8 ship gate.

## H0 — Baseline

- **Claim:** Completion in `video-blocks-manager.js` depends on `registerVideoEndHandler` firing; that handler is the `onEnded` adapter callback. For the YouTube adapter, the callback fires only on `state === YT.PlayerState.ENDED`.
- **Perturbation:** read `assets/shared/helpers/player/youtube-adapter.js` at SHA `b235d17` (trunk).
- **Trajectory:** divergent confirmation. `onEnded` (line 175) has a single trigger — state change to ENDED. `onTimeupdate` (line 133) also skips updates while state === ENDED but never coerces `currentTime → duration` when the player stalls short.
- **Mode:** deduction (read the code).

## H1 — YouTube end-screen videos stall before ENDED

- **Abduction:** the IFrame API for end-screen videos transitions PLAYING → PAUSED (or stays in CUED) at ~`duration − ε`, never emitting ENDED. Documented behavior in YouTube IFrame API; the reporter (zen-11171969) observed it in the wild and self-hosted media-library videos don't hit this path.
- **Null:** the bug is browser/extension specific, not a YouTube API quirk.
- **Perturbation:** check whether other adapters in the same dir compensate. Vimeo and videopress emit native `ended` events through their SDKs — no tolerance needed there. Self-hosted `<video>` fires `ended` from the HTML spec. So the YouTube adapter is the only one that both polls state and depends on a discrete ENDED signal. Class-of-bug consistent with reporter.
- **Mode:** abduction + deduction. Confidence 80%.

## H2 — Tolerance window in `onEnded` is sufficient

- **Claim:** a 1 s tolerance on `currentTime ≥ duration − 1` fires the completion callback once and lets the Complete Lesson button enable, without changing semantics for videos that do reach ENDED (early-fire guard prevents double-callback).
- **Perturbation:** wrote `youtube-adapter.test.js` with five cases — ENDED-fires-once, tolerance-fires-when-no-ENDED, both-fire-once-via-fired-flag, no-fire-on-`duration === 0` (player not loaded yet), `onTimeupdate` reports duration when within tolerance. Ran on master: 2 fail / 3 pass. Applied fix: 9/9 pass (test file plus existing `round-with-decimals`).
- **Trajectory:** divergent confirmation. Fail-on-master / pass-on-fix gate holds.
- **Mode:** induction. Confidence 92%.

## H3 — No regressions in surrounding modules

- **Perturbation:** `npx jest assets/shared/ assets/js/frontend/course-video/`.
- **Result:** 15 suites / 57 tests pass.
- **Mode:** induction. Confidence 95% for the tested surface; e2e (Playwright) and real-browser YouTube IFrame behavior not run.

## Frontier (open)

- **F1:** real-browser verification against a YouTube video with end screens. Out of scope for autonomous pass.
- **F2:** tolerance value (1 s). Conservative — 0.4% of a 4-minute lecture. Reviewer may want it smaller or settings-driven.

## Reframe check

No reframe. Issue framing is correct, fix is local. Only durable observation: discrete-event APIs need tolerance windows when the event is unreliable — common knowledge.

## Provenance

- `git blame` on the affected region (lines 133–186) → all from Donna Peplinskie 2023-08-15. Baseline implementation, not a deliberate "no tolerance" decision.
- Pack confirms zero related open PRs.
- CONTRIBUTING: PR-per-issue (✓), soft test ask (✓ — colocated jest file added).

## Causal chain

YouTube IFrame API does not emit `ENDED` for some end-screen videos → adapter `onEnded` callback never fires → `registerVideoEndHandler` never sets `completed = true` → `enableCompleteLessonButton` is never called → student is locked out of Complete Lesson.

## Fix shape

`assets/shared/helpers/player/youtube-adapter.js` (+46 / −3):
1. Add module constant `END_TOLERANCE_SECONDS = 1`.
2. In `onTimeupdate`, when `currentTime ≥ duration − tolerance`, push an update at `duration` so the progress UI shows complete.
3. In `onEnded`, add a backup 250 ms poll plus a `fired` flag so the callback fires exactly once, whether via `ENDED` or via the tolerance crossing.

Plus `youtube-adapter.test.js` matching the existing colocated convention.

## Phase 8 gate

Diff is +46/−3 in one source file plus a new test file. Awaiting human go/no-go before pushing a branch or opening a PR.
