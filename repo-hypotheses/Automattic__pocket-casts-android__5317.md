# Automattic/pocket-casts-android#5317 — OOM on low-RAM device from background UI work

Reporter: `passy` (long-time Android engineer; recognized contributor-style intake — does the diagnosis themselves, files specific file:line + proposed fix, declines to PR only because it's their daily-driver phone).

Reporter's diagnosis: `PlayerHeaderFragment` collects eight flows via `collectAsState()` instead of `collectAsStateWithLifecycle()`. The 1 Hz `PlaybackState` emission in `PlaybackManager` then drives constant Compose recomposition while the app is backgrounded; the host fragment view still exists so the collection never stops. The continuous frame requests keep RenderThread busy; Android's process-state heuristic weighs Pocket Casts as foreground; on a 4 GB device it loses the kill comparison. Secondary: `ChapterProgressBar` invalidates unconditionally on every `progress` setter call.

## H₀ — Reporter's diagnosis matches the code at HEAD

- **Perturbation:** grep both files at base `fb4c13cd0f0865334bc7e23a7d28d88273ffaab2`.
- **Result (deduction, 99%):**
  - `PlayerHeaderFragment.kt` lines 231–239: exactly eight `collectAsState()` calls, all inside `onCreateView`'s composition body. The fragment view's composition outlives the lifecycle's STARTED state, so collection continues while backgrounded.
  - `ChapterProgressBar.kt` lines 22–27: `progress` setter unconditionally rebuilds `progressDrawRect` and calls `invalidate()`. No equality guard, no visibility check.
- **Trajectory:** divergent confirm. Reporter's claim is literal.
- **Edge:** check whether the codebase already uses `collectAsStateWithLifecycle` so the convention is established (avoids importing a pattern they reject).

## H₁ — `collectAsStateWithLifecycle` is the established convention in the player module

- **Perturbation:** `grep -rn collectAsStateWithLifecycle modules/features/player/`.
- **Result (deduction, 99%):** already in `UpNextFragment.kt`, `EffectsFragment.kt`, `BookmarksPage.kt`, `BookmarksFragment.kt`, `PlayerShelf.kt`, `ShelfBottomSheetPage.kt`, `ShelfRearrangeActionsPage.kt`. The dependency `androidx.lifecycle:lifecycle-runtime-compose` is already on the classpath.
- **Trajectory:** divergent confirm. The swap is idiomatic, not novel.
- **Edge:** check for behavioral differences that could surprise the reporter or maintainer.

## H₂ — Semantic change is bounded: collection pauses on STOPPED, resumes on STARTED, with the initial value

- **Perturbation:** read the AndroidX docs + the call sites' usage of the collected values.
- **Result (deduction, 92%):** `collectAsStateWithLifecycle` defaults to `Lifecycle.State.STARTED`. While the fragment's view-lifecycle is STOPPED (backgrounded), upstream emissions are not consumed; on STARTED the latest value is re-collected. All eight values consumed here are UI-visibility-gated (player open state, transcript open state, header data, artwork state, active ad, playback notice, podcast colors). Acting on a stale value while backgrounded would be wrong anyway — the user can't see it.
- **Trajectory:** convergent. No correctness regression.
- **Edge:** check the ChapterProgressBar guards for behavioral correctness.

## H₃ — `ChapterProgressBar` guards are safe at the boundaries

- **Perturbation:** trace the call sites and the View lifecycle.
- **Result (deduction, 95%):**
  - `if (field == value) return` — float equality on a progress fraction. The 1 Hz emission can produce the same fraction across ticks within a chapter; suppressing the no-op draw is strictly cheaper and visually identical.
  - `if (isAttachedToWindow && isShown) invalidate()` — `invalidate()` on a detached/hidden View is already a no-op for redraw, but it still walks parent visibility. Cheap guard; matches reporter's suggestion verbatim.
  - First-set boundary: `progress = 0f` default → first non-zero set passes the equality guard. `onSizeChanged` recomputes `progressDrawRect` independently, so a measure pass while the View is detached doesn't lose any state.
- **Trajectory:** convergent. The setter is a back-pressure filter, not a state machine change.
- **Edge:** verify the fix shape doesn't conflict with any in-flight work.

## H₄ — No competing PR or sibling fix in flight

- **Perturbation:** context pack lists open PRs matching the issue keywords and operator's prior PRs on this repo.
- **Result (induction from pack, 95%):** zero related open PRs, zero prior PRs from `kimjune01`. Default branch CI is green at base.
- **Trajectory:** divergent confirm. Open lane.
- **Edge:** none. Frontier closes.

## Provenance check

- The eight `collectAsState` call sites entered as the composable header was introduced (shallow clone limits blame; the surrounding file recently bumped `media3 1.10.0 → 1.10.1` unrelated). The pattern reads as a migration default rather than a deliberate choice — sibling files in the same module already migrated to the lifecycle-aware variant, suggesting the migration just didn't reach this file.
- Reporter explicitly asks the design question: *"Is there any particular reason not to use `collectAsStateWithLifecycle()` in `player/view/PlayerHeaderFragment.kt`?"* The fix shape is the answer they wrote into the issue.

## Reframe check

The issue title says "background bitmap processing" but the reporter's body retracts that and points at Compose state collection driving render-thread frames. The bitmap framing is a Perfetto-trace surface symptom; the cause is the 1 Hz tick * always-active collection. No reframe needed beyond noting the title is downstream of the real cause.

## Graph state

| Node | Status | Trajectory | Confidence |
|------|--------|------------|------------|
| H₀ reporter's diagnosis literal at HEAD | confirmed | divergent | 99% deduction |
| H₁ lifecycle-aware variant is module convention | confirmed | divergent | 99% deduction |
| H₂ semantic delta is bounded and correct | confirmed | convergent | 92% deduction |
| H₃ ChapterProgressBar guards safe at boundaries | confirmed | convergent | 95% deduction |
| H₄ no in-flight competing work | confirmed | divergent | 95% induction |

Frontier closed. Proceed to ship readiness.

## Fix

Branch `fix-player-background-recomposition` at base `fb4c13cd0f0865334bc7e23a7d28d88273ffaab2`. Two files, 11/10 lines:

- `PlayerHeaderFragment.kt`: swap import `androidx.compose.runtime.collectAsState` → `androidx.lifecycle.compose.collectAsStateWithLifecycle`; rename the eight call sites.
- `ChapterProgressBar.kt`: add `if (field == value) return` and gate `invalidate()` on `isAttachedToWindow && isShown`.

No tests. The module has no UI/View tests for fragments or custom Views — only viewmodel tests. Following the existing convention (the fix is a one-line guard + a rename to an already-imported library variant).
