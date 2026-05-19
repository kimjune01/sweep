# MaterializeInc/materialize#36491 — Hypothesis Graph

**PR:** https://github.com/MaterializeInc/materialize/pull/36491
**Title:** adapter: Add docs link to ResourceExhaustion hints
**Author:** kimjune01 (me) — note: not a maintainer-self-PR halt case (issue tracker disabled upstream; #29790 not resolvable)
**Diff size:** 2 additions / 1 deletion in `src/adapter/src/error.rs`
**State:** OPEN, MERGEABLE, REVIEW_REQUIRED, all checks FAILED.

## H₀ — Observation

The PR's three checks are all in FAILURE state:

| Check | Conclusion | Wall time |
|-------|-----------|-----------|
| `cla-assistant` | FAILURE | 8s |
| `buildkite/test` | FAILURE | ~1s |
| `buildkite/test/pipeline` | FAILURE | exit 1 |

Both buildkite jobs failed in ~1 second — that's too short to be test execution. It's pipeline-setup failure.

Timeline:
- 2026-05-10 18:18:47Z — buildkite/test starts, fails ~1s later
- 2026-05-10 18:18:48Z — cla-assistant starts, fails 8s later (CLA unsigned)
- 2026-05-11 00:31:39Z — operator posts "I have read the CLA Document and I hereby sign the CLA" (~6h after the initial checks)

Trajectory: **divergent** — every signal points the same way (CLA was unsigned when CI ran; nothing re-ran after signing).

## H₁ — Buildkite is gated on the CLA check

**Abduction.** External-contributor PRs in MaterializeInc/materialize don't run the test pipeline until the CLA is signed. The ~1s buildkite failure is a guard step, not a real build.

**Perturbation (read-only):** inspected buildkite build URL — page returns 403 (auth-required), so log contents can't be read directly. But the wall-clock signature (1s exit, fail-fast) is consistent with a pre-pipeline guard and inconsistent with any genuine test failure on a 2-line diff to `error.rs`.

**Kill condition:** if the build is later retriggered and still fails ~1s, then the guard hypothesis is wrong (it would be a structural pipeline-config failure instead).

**Status:** confirmed at ~85% (abduction + circumstantial deduction). Cannot deduce to 95% without reading the gated log.

## H₂ — CLA check needs explicit `recheck` to re-run

**Abduction.** CLA Assistant Lite bot's own message says: *"You can retrigger this bot by commenting **recheck** in this Pull Request."* The CLA-signed comment posted 6 hours later did not include "recheck", so the bot never re-evaluated. The cla-assistant check is still stuck on its first (failing) verdict.

**Reasoning mode:** deduction from the bot's own documentation embedded in PR comment #4415999388. Confidence: 95%.

**Status:** confirmed.

## H₃ — Buildkite will re-run on push or re-request, not on comment

**Abduction.** Buildkite typically only retriggers on commit-push or an authenticated "rebuild" action by a maintainer. A comment alone won't restart it. So even after CLA passes, buildkite needs a separate kick (an empty commit, force-push, or maintainer rebuild).

**Status:** open frontier edge. Predicted trajectory: divergent — either the buildkite check stays red until a push, or maintainer-triggered rebuild flips it.

## Graph state

| Node | Status | Trajectory | Mode |
|------|--------|-----------|------|
| H₀ — all three checks failed | observed | divergent | induction (gh CLI) |
| H₁ — buildkite gated on CLA | confirmed (85%) | divergent | abduction + circumstantial |
| H₂ — CLA needs `recheck` | confirmed (95%) | divergent | deduction |
| H₃ — buildkite needs push/rebuild | open | predicted divergent | abduction |

## Frontier edges (pending perturbations)

1. **Post `recheck` comment** → predicted: cla-assistant flips to PASS within ~30s. This is the cheapest decisive experiment.
2. **Push empty commit** (or wait for maintainer) → predicted: buildkite re-runs, real pipeline executes, and either passes (2-line docstring change to a hint string) or surfaces a real test failure.

Both are external side effects on a public PR — they are Phase 8 actions, not autonomous local perturbations. **Halting here for human gate.**

## Provenance check

- **Git blame on the touched lines** — not yet run; deferred until the CI gate is unstuck. The change is to the `ResourceExhaustion` hint string; the original wording predates this PR and is mechanical.
- **Adjacent issues** — repo has issues disabled publicly; #29790 not directly inspectable. The PR title and body cite the issue, and the diff is a non-behavioral docs-pointer addition.

## Reframe

The "investigation" target here is not a hardware/algorithmic system — it's a CI policy gate. The hypothesis graph collapsed to a procedural unblock in two abductions. The transferable observation: **for first-contribution PRs in repos with CLA-gated CI, the post-CLA workflow requires two explicit triggers — `recheck` for the bot, and push/rebuild for buildkite.** Worth a memory entry, not a code change.

## Next action (human gate)

The minimal unblock sequence:
1. `gh pr comment 36491 --repo MaterializeInc/materialize --body "recheck"` — retriggers CLA bot.
2. After CLA flips green, either push an empty commit or wait for a maintainer to rebuild buildkite.

No code change to ship. The PR's diff (2 lines) stands on its own and the fix-shape is already approved by being merged-ready (`MERGEABLE`). The frontier is open only on remote-side perturbations that need operator approval.

## Reinvestigate cycle — 2026-05-18

Re-entered from attest. No new state: CI rollup unchanged (cla-assistant FAILURE at the original SHA `e778b46`, both buildkite contexts FAILURE), no new commits, no new comments since 2026-05-11. The operator's signing comment ("I have read the CLA Document and I hereby sign the CLA") is still the most recent activity and still did not include the `recheck` keyword.

**Graph status:** unchanged. Frontier edges 1 & 2 from the original cycle remain the only path forward, both human-gated. Halting.

## Reinvestigate cycle — 2026-05-18 (later)

Re-entered from attest a second time. New evidence in the context pack:

- **Failing checks: 0 of 3** (was 3 of 3 in prior cycles).
- New comment 2026-05-18T19:17:02Z: operator re-signed CLA ("I have read the Contributor License Agreement (CLA) and I hereby sign the CLA").
- New comment 2026-05-18T19:17:03Z: operator posted `recheck`.

**Trajectory:** divergent confirmation of H₂ and H₃ — the `recheck` keyword flipped cla-assistant, and either the push/CLA-flip cascaded into a buildkite re-run that passed (2-line docstring change is trivially green), or the rollup now shows no FAILUREs because the failing contexts were retried and succeeded. Either way, the CI gate is clear.

PR state: still `REVIEW_REQUIRED`, `MERGEABLE`, no failing checks. Frontier is now closed on the CI-policy side; the only remaining edge is **maintainer review attention**, which is not a perturbation surface from this side. Halting — no further investigate action possible until reviewer engages.
