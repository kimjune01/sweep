# Triage Graph: elemaudio/elementary

## MAINTAINER PREFERENCES

- **Target branch**: main
- **AI policy**: None specified (cached as permissive in `~/.sweep/cache/ai-policy/`).
- **Review style**: Solo-maintainer cadence; bug fixes with reproducers preferred.
- **Test convention**: Jest; the JS package's TS transform config is currently broken on `main` (pre-existing, not a regression).

## ISSUE SCORES

### Attempted

| # | Title | Score | Status | Branch |
|---|-------|-------|--------|--------|
| 73 | `metro` event type missing from `EventTypes` | 8 | shipped (PR #80) | fix/metro-event-type |

## FIX DETAILS

### #73 / PR #80: fix/metro-event-type

**Root cause**: The TypeScript `EventTypes` interface in `Events.ts` did not include the `metro` event, so `core.on('metro', callback)` failed type-checking even though the C++ `MetronomeNode::processEvents` emits the payload at runtime.

**Fix**: Add `metro` entry to `EventTypes` matching the C++ payload shape exactly. Maintain alphabetical ordering and style consistency with existing entries (`meter`, `scope`, `snapshot`).

**Attestation**:
- `tsc --noEmit` compiles the type-level test cleanly.
- Negative check: removing the `metro` line produces `TS2345`.
- Jest suite skipped (pre-existing TS-transform misconfig on `main`, not a regression).
- Reverted an unrelated `typescript ^6.0.3` devDep bump that slipped into the working tree.

**Hypotheses exercised**:
- **H1 (issue-first PRs merge)**: PR cites `Fixes #73`, ships a single-line type addition with negative check.
- **H4 (bug fix, not feature)**: type-completeness fix; no API surface change.
- **H6 (receipts > prose)**: PR body lists `tsc` evidence and a falsification check; this graph is the public reasoning trace.

## EXPERIMENT

`hg_in_body_2026-05-14`: inject a link to this graph into the PR body to test whether explicit reasoning provenance correlates with merge / review-engagement.
