# njbrake/agent-of-empires#1177 — Android Chrome PWA: keyboard occludes cockpit composer

**Issue:** https://github.com/njbrake/agent-of-empires/issues/1177
**Reporter:** @Seluj78 (Jules Lasne — active contributor, not the repo owner)
**Maintainer:** @njbrake
**Repo policy:** MIT, no LLM ban (project is itself a tool for managing LLM agents — Claude-authored prose explicitly disclosed in issue and welcome).
**Existing PRs:** none for this issue. Reporter has unrelated open PR #1179 (logging).
**Adjacent merged:** #1150 (viewport `interactive-widget=resizes-content`), #1152 (composer bottom-gap collapse), #880 (SIGWINCH stability — the constraint behind the height pin).

## Pre-investigation note: the issue body *is* a hypothesis graph

@Seluj78's writeup already contains the full diagnosis: root cause layered (1)-(4), three candidate fixes (A/B/C), kill conditions for each, recommendation (A + C). Phases 1–3 are pre-done. This document's job is **Phase 2.5 (provenance check)** + **pushout disagreement scan** + **Phase 4.5 reframe test** + **Phase 5 prework gate**.

Investigation is therefore a *validation* pass, not a *generation* pass. Confidence ceiling on the surviving hypothesis is high (the reporter did the deduction work), but the surface for disagreement is small.

## H₀ — App-root pixel pin overrides `interactive-widget=resizes-content` on Android Chrome PWA

**Claim.** `web/index.html:5` sets the viewport hint that asks Chrome 108+ to shrink the layout viewport when the soft keyboard opens. But `App.tsx:721-724` writes an inline pixel `height: stableViewportHeight` to the root `<div>`, which wins over the percent-based `h-dvh` Tailwind class. When the keyboard opens, the layout viewport would shrink — but the root stays at the pre-keyboard height, the composer (last child of a `flex-col`) stays at its 800px-from-top position, and Android Chrome's "scroll-focused-input-into-view" doesn't fire because the input is inside `overflow: hidden`. First keypress triggers a reflow that finally scrolls the activity-panel parent.

**Trajectory:** divergent-for (deduction from code reading, line numbers verified below).

**Provenance check (verified against `/tmp/aoe-1177` shallow clone at HEAD):**

- `web/index.html:5` — viewport meta with `interactive-widget=resizes-content` ✓
- `web/src/App.tsx:720-724` — `rootStyle = isMobile && stableViewportHeight > 0 ? { height: '...px' } : undefined` ✓
- `web/src/App.tsx:744-746` — `<div className="h-dvh ..." style={rootStyle}>` ✓ (inline px height wins over Tailwind class)
- `web/src/components/cockpit/CockpitView.tsx:190, 305` — composer is last child of `flex h-full flex-col` ✓
- `web/src/components/cockpit/Composer.tsx:75-88` — `composerWrapperLayout` drops `pb` when `keyboardOpen` but does not reposition ✓

All cited code matches.

**Origin of the pin.** PR #880 ("stop SIGWINCH on every soft-keyboard cycle on mobile", njbrake). The pin is load-bearing for the terminal substrate — without it, every keyboard show/hide SIGWINCHes claude in xterm.js. Removing the pin globally would regress terminal sessions. Confidence: deduction, 95%.

## Pushout — disagreement scan against the reporter's recommendation (A + C)

The reporter recommends:
- **(A)** Gate the height pin on `activeSubstrate === "terminal"` so cockpit sessions get `h-dvh` shrinkage for free.
- **(C)** `scrollIntoView({ block: "end" })` on focus as a defensive safety net.
- Skip **(B)** (`position: fixed` driven by `visualViewport`) unless A regresses.

### Where I agree

- (A) is the smallest correct fix. Verified: `activeSession?.cockpit_mode` is already in scope at `App.tsx:240` and is already the gate that picks `<CockpitView>` vs `<TerminalView>` at `App.tsx:626`. The "open question" in the issue about needing a global `activeSubstrate` selector is over-careful — the boolean exists. Fix is roughly one line:
  ```ts
  const rootStyle =
    isMobile && stableViewportHeight > 0 && !activeSession?.cockpit_mode
      ? { height: `${stableViewportHeight}px` }
      : undefined;
  ```
  Plus a `useEffect` dependency check on `activeSession?.cockpit_mode` (it'll be picked up automatically by re-render).

- (B) is correctly tabled. Larger refactor, mid-animation `visualViewport` events need debouncing, and it would re-introduce some of the SIGWINCH surface that #880 closed.

### Where I'd push back

**(C) is more than a "no-cost safety net" — under (A) it is dead weight, and without (A) it does not fix the bug.** The reporter's own caveat is correct: `scrollIntoView` only works if there's a scrollable ancestor with content below the focus target. With the height pin in place, the activity panel has no content below the composer (composer is anchored to bottom of fixed-height container). Once (A) lands, the whole container shrinks, and the composer is already above the keyboard — `scrollIntoView` has nothing to do. Recommending (C) anyway costs a 300ms timer, a ref, and a focus listener; in exchange it covers exactly one regression case (A landed but `cockpit_mode` is somehow false in a future cockpit path).

**Recommendation: ship (A) alone.** Add (C) only if a substrate-switch transition is observed to leave the composer mis-positioned. Smaller diff, easier to review, easier to revert.

**Substrate-switch transition (the reporter's other open question)** — terminal → cockpit while keyboard is open. With (A) alone: pin drops, root snaps from `stableViewportHeight` px to `h-dvh` (which on Android with `resizes-content` shrinks to viewport-minus-keyboard). One frame of layout jump. Acceptable: substrate switch is a deliberate user gesture, not a hot path. Cockpit → terminal while keyboard is open: pin appears, root grows back. Composer is in cockpit on the way out so it doesn't matter. Confidence: abduction, 70% — verify on device before claiming "no regression."

## Frontier edges

1. **Will (A) regress the existing iOS PWA fix from #1145?** That fix relied on `interactive-widget=resizes-content` *plus* the height pin to prevent the iOS document-scroll. iOS Safari treats `resizes-content` differently than Android Chrome. Need device verification: install PWA on iOS, open cockpit session, tap composer, confirm composer is visible above keyboard AND no document-scroll happens. *Predicted classification:* convergent — `h-dvh` should resolve correctly on iOS post-#1145, but verify on a real device.

2. **Does `h-dvh` actually shrink on Android Chrome PWA with `interactive-widget=resizes-content`?** The reporter asserts yes. The MDN/Chrome docs say yes for Chrome 108+. *Predicted classification:* convergent. Worth a one-line confirm during prework — load a stripped repro page with `height: 100dvh; border: 1px solid` and confirm visually.

3. **Multi-line composer growing past `max-h-[200px]` with keyboard open** — listed as out-of-scope. Likely still works post-(A) because the whole container shrinks, but flag for the manual test.

## Reframe test (Phase 4.5)

Does the surviving hypothesis answer the original question, or replace it? **Answers.** "Why is the composer occluded?" → "Because the App root is pinned to no-keyboard height for a constraint that doesn't apply to cockpit." Fix shape follows directly. No reframe; this is a straightforward code change.

## Decision: prework + readiness, do not ship without maintainer approval

@njbrake is the maintainer. @Seluj78 (reporter) is a co-contributor who already did the diagnostic work. The polite path is to **comment on the issue with the validation + recommendation** rather than racing to a PR — the reporter may want to land their own fix, and the diff is small enough that they don't need it written for them.

**If the maintainer or reporter wants a PR from this account**, the prework is trivial:

- **Branch:** `fix/cockpit-keyboard-android-pwa` (matches the repo's `fix/` naming convention).
- **Change:** one boolean in `App.tsx:721-724`.
- **Test:** add a unit test for the rootStyle logic — `rootStyle === undefined` when `cockpit_mode` is true, `{ height: "<n>px" }` when false. The repo already unit-tests layout helpers (`Composer.layout.test.ts`), so the pattern exists.
- **Manual verification before PR:** Android Chrome PWA (cockpit session — composer visible above keyboard, no first-keystroke-required reflow) + iOS Safari PWA (terminal session — no regression of #1145 / #880) + substrate switch mid-keyboard (one-frame jump is acceptable, total layout collapse is not).
- **PR body:** link to issue #1177, reference #880 and #1145 as the constraints that gate the pin, one-line description of the change, manual-test matrix.

## Graph state

| Node | Status | Mode | Confidence |
|---|---|---|---|
| H₀: pixel pin overrides `resizes-content` | confirmed | deduction (code read + line-verified) | 95% |
| Origin: pin from #880 for SIGWINCH stability | confirmed | provenance (gh + git blame proxy) | 95% |
| Fix shape (A): substrate-gated pin | proposed | abduction → deduction | 90% |
| (B): `position: fixed` + visualViewport | tabled | abduction | (not pursued) |
| (C): `scrollIntoView` on focus | argued against | deduction (reporter's own caveat) | 80% |
| Frontier 1: iOS regression risk | open | needs device perturbation | — |
| Frontier 2: `h-dvh` shrinkage on Android Chrome PWA | open | needs device perturbation | — |
| Substrate-switch mid-keyboard | open | abduction | 70% |

## Halt reason

Hypothesis-grounded; fix shape is mechanical; PR-shaped change but **author etiquette favors commenting on the issue with the validation rather than racing the reporter to a PR**. Awaiting human go/no-go on (i) post a validation comment on #1177, (ii) open a PR ourselves, (iii) do neither and let @Seluj78 / @njbrake handle it.
