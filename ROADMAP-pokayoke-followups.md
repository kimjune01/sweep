# Pokayoke intake follow-ups

Three deferred items from the 2026-05-18 bug hunt on the new
`amend_cycle` / `reqa_cycle` / `reinvestigate_cycle` intake guards.
Listed cheapest → most architectural.

## 1. `is_pr_done` helper for engagement-lane intakes

**Problem.** `is_pr_approved()` (sweep/pokayoke.py:96) returns a skip
on bare `reviewDecision == "APPROVED"` (and `member_approved_over_cr`).
But the classifier in `pr_state.py:579-594` deliberately keeps approved
PRs in rotation when CI is red — routing them to `reqa` (mechanical),
`reinvestigate` (non-mechanical), or `sign` (CLA-class). The new
`reqa_intake` and `reinvestigate_intake` therefore drop exactly the
PRs the classifier expects them to remediate.

**Fix.**
- New helper `is_pr_done(repo, pr) -> SkipReason | None` returning a
  skip iff `reviewDecision == APPROVED` AND `mergeable == MERGEABLE`
  AND `ci == green` — the same predicate `pr_state.py:592` uses for
  the `done` bucket.
- Swap `is_pr_approved` → `is_pr_done` in `reqa_intake`,
  `reinvestigate_intake`. Leave `is_pr_approved` available for any
  caller that genuinely wants the broader check (none today).

**Risk.** Low. The bucket-true contract is already encoded in the
classifier; we're just lifting it into the intake.

**Smoke.** Replay an approved-with-red-CI card through reqa; confirm
it now proceeds instead of skipping.

## 2. Normal-path `reinvestigate_done` needs an `outcome` field

**Problem.** Skip path now emits `outcome="skipped"` (R1.3 fix), but
the existing `reinvestigate_done` event at reinvestigate.py:107-115
doesn't set `outcome` at all. `retro skill-stats` (cli/retro.py:551)
buckets by `outcome`, so every non-skip reinvestigate run lands in the
`"-"` bucket. Operator sees `reinvestigate -> -` and can't tell
shipped / no-fix / human-gated / defer apart.

**Fix.** Derive a stable `outcome` on the non-skip path from the
existing flags:
- `result.get("no_fix")` → `"no_fix"`
- `result.get("human_gated")` → `"human_gated"`
- `result.get("artifact_fresh") and result.get("produced_pr")` → `"shipped"`
- else → `"defer"` (or whatever matches the actual investigate vocab)

Emit `outcome=<derived>` on the `reinvestigate_done` event. Keep
`skipped` on the skip path so the vocabulary is consistent.

**Risk.** Low. Read-only addition to the event payload.

**Coupled to #3.** If #3 changes the return shape of
`investigate_cycle`, redo the derivation against the new contract.

## 3. `reinvestigate_cycle` ↔ `investigate_cycle` return contract drift

**Problem.** `reinvestigate_cycle` (reinvestigate.py:119-130) routes
the engagement lane by reading `artifact_fresh`, `branch`, `no_fix`,
`human_gated` off `investigate_cycle`'s return dict. Codex flagged
that the shared investigate flow may no longer return that shape on
the normal path — it emits `investigate_done`, kicks `switch`, and
returns the raw skill-runner result. If so, `artifact_fresh` is
falsey and the `kick_reqa_card(...)` block never fires; shipped
engagement-lane fixes silently miss the
`reinvestigate → reqa → respond` handoff and fall onto the
production `qa` lane instead.

**Fix (two options).**

- **Option A — explicit return contract.** Give `investigate_cycle`
  a typed return (TypedDict or dataclass) that always carries
  `artifact_fresh`, `branch`, `no_fix`, `human_gated`. Callers
  (`reinvestigate_cycle`, anyone else) keep their current shape.
  Lower risk; preserves the existing routing seam.

- **Option B — lane-aware routing via switch.** Stop deriving lane
  routing from the investigate return. Let `switch` see a lane hint
  on the card (engagement vs production) and route shipped verdicts
  to `reqa` when the lane is engagement, `qa` when production.
  Higher risk; cleaner architecturally — one router instead of two
  divergent routing predicates.

**Investigation needed first.** Read `investigate_cycle` and
confirm whether the regression Codex described actually happened. If
the return still carries those keys, this is a false alarm and the
item closes. If not, choose A vs B.

**Risk.** Medium-high. This is the routing brain of the engagement
lane; getting it wrong means PRs handed off to the wrong actor.
Pair with a replay test that walks one shipped engagement fix end to
end and asserts which actor it landed at.

## Suggested order

1. **#1 (`is_pr_done`)** — small, mechanical, unblocks correct
   classification today.
2. **#3 investigation** — confirm whether the routing bug exists.
   Cheap to verify, decides #3's scope.
3. **#3 fix** (A or B) — only after the investigation lands.
4. **#2 (`outcome` field)** — do after #3 so the derivation matches
   the final contract.

## Provenance

Bug-hunt session 2026-05-18, rounds 1-3, codex (GPT-5.5) on the
pokayoke intake edits. Findings R2.2, R2.3, R3.1 deferred from
in-scope fixes.
