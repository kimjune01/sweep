# Hypothesis graph: mattgodbolt/pal-decoder#1

**Issue:** Pipeline only syncs at start of capture on exact frame boundary
**Filed by:** mattgodbolt (sole repo maintainer; sole committer)
**Repo state:** main is post-issue; `findFieldOneSample` already added in commit a340938 (2026-04-19), but does not actually solve the issue (reproduced below).

## Verdict: HALT pre-PR — maintainer self-authored design memo

Recommended downstream action: do NOT ship a PR. Surface to operator inbox.
Investigation work below is preserved as evidence.

### Halt rationale

- **Sole-committer repo.** `git log --format='%an' --all | sort -u` returns
  only "Matt Godbolt." No external contributors merged to date.
- **Issue reporter == maintainer.** Issue author is `mattgodbolt`.
- **Body reads as a design memo, not a bug report.** The issue body lists
  three labelled "Root causes" inside Matt's own code, references his own
  encoder's stage-2 design choices ("The encoder doesn't emit equalising
  pulses (documented as intentional for stage 2)"), and adds a forward-looking
  "Knock-on σ alignment risk" section. This is the author writing a TODO to
  themselves while their understanding is hot, not soliciting outside fixes.
- **Active staged design in flight.** Recent commits a340938 ("Robust
  field-1 detection that survives mid-frame start offsets") and f6e9923
  ("Real PAL: half-line-offset interlace, two-field-PLL decoder") show
  Matt is mid-redesign of the exact code path this issue critiques. Any
  PR I push lands inside his moving target.
- **Pattern match.** [[feedback_maintainer_self_pr]] — halt before
  investing in WIP-PR when reporter and likely author are the same person.
  No WIP PR exists yet, but the conditions for one converging on the same
  fix in a short window are present.

## H₀: bug reproduces on current main

**Perturbation:** ran the exact reproduction script from the issue body
against current `main`.

```
shift=100 lines=0:    PSNR 27.48 dB    (expected baseline)
shift=56850 lines=50: PSNR 8.49 dB
shift=227100 lines=200: PSNR 8.49 dB
shift=354220 lines=312: PSNR 8.49 dB
shift=454100 lines=400: PSNR 5.22 dB
```

**Trajectory:** divergent. Bug present in main; `findFieldOneSample`
addition (a340938) did not fix it. `findFieldOneSample` returns numerically
plausible values but locks to wrong frame phase. Issue is genuine, not stale.

**Status:** confirmed.

## H₁: the documented 312-vs-313-line discriminator does not hold for this encoder

**Source-of-claim:** `src/vsync.js:1-19` header comment asserts: "the
spacing between consecutive groups alternates — 312 lines from field 1 to
field 2, 313 lines from field 2 back to field 1 of the next frame. The
field-1 group is the one whose outgoing spacing is *shorter*."

**Perturbation:** read `src/timing.js`:
- `FIELD_2_START = 312 * LINE_SAMPLES + HALF_LINE_SAMPLES = 354688`
- `HALF_LINE_SAMPLES = 568` (rounded from true 567.5)
- `FRAME_SAMPLES = 625 * 1135 = 709375`

Spacings between consecutive broad-pulse-group starts:
- F1 → F2:        `354688 - 0      = 354688 samples`
- F2 → next F1:   `709375 - 354688 = 354687 samples`

**Trajectory:** divergent against the comment. The two spacings differ by
1 sample (rounding artifact of 568 vs 567.5), with F1→F2 *longer*, not
shorter. The algorithm's `if (spacings[i] < spacings[i + 1])` test is
strictly false for this encoder's signal, so the 3-group branch is dead
code — even when there are 3+ groups, it falls through to `groups[0]` and
silently picks whichever group it saw first. Two-group case (the
reproduction) also falls through.

This is half-line-interlace PAL geometry: both field-to-field gaps are
~312.5 lines in time. The 312/313 alternation is an NTSC-shaped intuition;
in 625/50 PAL the half-line offset makes the gaps symmetric.

**Status:** confirmed (deduction from constants).

## H₂: a usable discriminator exists — broad-pulse line-phase residue

**Abduction.** Field-1 broad pulses sit at integer multiples of
`LINE_SAMPLES` (offset 0 mod 1135). Field-2 broad pulses sit at
`FIELD_2_START + k*LINE_SAMPLES = 354688 + k*1135`, all of which are
`568 mod 1135`. So *every* broad pulse in the source signal carries a
field tag in its `position mod LINE_SAMPLES` residue: 0 → F1, 568 → F2.

After a buffer shift `s`, the residue becomes `(-s) mod 1135` for F1 and
`(568 - s) mod 1135` for F2 — the absolute residue is hidden but the
*difference* between groups is preserved: groups of opposite field
differ by ~568 in residue; groups of same field share a residue.

**Predicted perturbation (not run — halt-before-PR):**
1. Group broad pulses (existing code).
2. Compute median position-mod-LINE_SAMPLES per group.
3. Cluster groups into two residue bins (separation ≈ 568 ± slop).
4. To pick which bin is F1: use narrow-sync edges. Field-1 lines'
   narrow syncs share F1's residue; field-2 lines' share F2's. The bin
   whose residue matches the *majority* of narrow-sync edges (since
   F1 and F2 each contribute ~305 narrow syncs but the active-picture
   region is symmetric) is ambiguous — need a second tiebreaker.
5. Tiebreaker candidate: F1's broad group is immediately followed by
   ~305 narrow-sync edges at F1's residue; F2's by ~305 at F2's
   residue. So a group's *outgoing* narrow-sync residue identifies its
   field directly.

**Status:** unproven (not implemented). Filed as the strongest candidate
fix shape to surface to the operator / maintainer.

## H₃: equalising-pulse path is out of scope per maintainer

Issue body §3: "The encoder doesn't emit equalising pulses (documented
as intentional for stage 2)." The maintainer has explicitly scoped out
the textbook PAL discriminator and is building an alternative. This
reinforces the halt — proposing the equalising-pulse path would
contradict his stated design direction.

## Frontier (open edges, not pursued)

- E₁: implement H₂ (residue-based discriminator) and re-run repro.
- E₂: probe `buildLineMetadata`'s σ-parity sensitivity to a 1-line F1
  offset (the "knock-on" risk in the issue body).
- E₃: check whether `findFieldOneSample`'s `+ 0.5` fudge interacts
  badly with the half-line-rounded `FIELD_2_START` for F2-locked
  pipelines.

All three left open by design — they belong to the maintainer's stage-2
work, not to a drive-by contributor.

## Reasoning-mode table

| Claim | Mode | Confidence |
|-------|------|------------|
| Bug reproduces on main | Induction (ran the script) | 99% |
| 312/313 comment is wrong for this encoder | Deduction (read constants) | 98% |
| Residue discriminator would work | Abduction (geometric argument) | 70% |
| Halting is the right call | Pattern-match against [[feedback_maintainer_self_pr]] | 90% |

## Provenance

- Comment block `src/vsync.js:1-19` authored in a340938 by mattgodbolt.
- Encoder half-line rounding in `src/timing.js:60` (`HALF_LINE_SAMPLES = 568`,
  comment notes "slightly rounded from the true 567.5"). Author aware.
- Codex/Gemini filtering skipped (halt before fan-out).
