# robinraju/release-downloader#944 — Investigation

**Subject:** Our own open PR #944 ("docs: clarify fileName uses minimatch glob patterns") against `robinraju/release-downloader`. Closes upstream issue #778.

**Question:** Is this PR sound, or is it overscoped in a way that hurts merge probability?

**Mode:** Self-review of an in-flight PR. Phase 8 (ship) is moot — the PR already exists. The output is a recommendation: leave as-is, shrink, or split.

## H₀ — Observation

Issue #778 is a single, narrow ask from `mirandaasm` (2025-03-07): "Please mention in the docs that `inputs.fileName` matches against minimatch patterns." No bug, no behavior change requested. The reporter even says "feel free to close this issue whenever you want."

PR #944 (kimjune01, 2026-05-12) modifies 5 files / +121 / -26:

| File | Change | Asked for in #778? |
|------|--------|--------------------|
| `README.md` | Replace "wildcard pattern" with "minimatch", add 3 examples | **Yes** |
| `action.yml` | Update `fileName` description with minimatch link | **Yes** |
| `__tests__/main.test.ts` | Add `{a,b}` and `?` glob tests | Stretch (covers docs claims) |
| `__tests__/main.test.ts` | Add "Fail when no fileName / tarBall / zipBall" test | **No** (tests a behavior the PR itself introduces) |
| `src/release-downloader.ts` | Refactor `resolveAssets` error path — throw new `ConfigError` when nothing specified | **No** |
| `src/release-downloader.ts` | Add `path.basename()` sanitization on output filename | **No** |
| `src/release-downloader.ts` | Add `.destroy()` calls on stream errors | **No** |
| `src/unarchive.ts` | Wrap `zip.extract` in try/finally for `zip.close()` | **No** |

H₀ classification: **divergent against PR scope** — the PR is doing five things; only two of them were asked for.

## H₁ — Overscoped against issue

**Hypothesis:** Maintainer review probability drops as unrelated concerns are bundled, especially in a low-traffic repo where the maintainer reviews slowly.

**Null:** Bundling related-looking hygiene fixes into a docs PR is harmless or welcomed.

**Perturbation (read):** Recent commit history shows the maintainer (`robinraju`) has merged only dependabot bumps + chore commits in the last ~20 commits. Last substantive feature merge was `3bd996f` (issue #729 — single concern). Issue #778 sat open ~14 months with one community comment, no maintainer engagement. CONTRIBUTING.md exists but says nothing about PR scoping.

**Trajectory:** **convergent** — maintainer cadence and history both point to "merges small, focused PRs; ignores big ones."

**Kill condition for null:** if maintainer had a history of merging refactor-PRs, the null would survive. They don't.

**Status:** **confirmed (high).** PR is overscoped relative to repo norms. Mode: induction (read history) + deduction (matched ask to diff).

**Edge:** which of the 4 unrequested changes is defensible enough to keep, vs. split off?

## H₂ — ConfigError refactor is a behavior change

**Hypothesis:** Replacing the silent-empty-list path with a thrown `ConfigError` changes the public contract.

**Perturbation (read):** On master, `resolveAssets` returns `[]` when `fileName === '' && !tarBall && !zipBall`. Caller code in `download()` then proceeds to `downloadReleaseAssets([], ...)` which presumably no-ops and sets empty outputs. The PR throws `ConfigError('No assets to download. Specify fileName, tarBall, or zipBall.')` instead.

**Trajectory:** **divergent.** This is observably different behavior. A workflow that previously ran with all three inputs empty (maybe accidentally, maybe by config) now fails the action.

**Status:** **confirmed.** This is a behavior change, not a refactor. Whether it's desirable is a separate question — but it's not what #778 asked for, and shipping behavior changes inside a docs PR is exactly the kind of thing reviewers flag.

**Risk:** medium. Defensible on its own merits as a separate PR (early-fail on misconfig is generally good), but smuggled here.

## H₃ — Path sanitization is defense-in-depth, near no-op in practice

**Hypothesis:** `path.basename(fileName)` on the output filename has no observable effect under normal use because GitHub's release-asset API rejects asset names containing path separators.

**Perturbation (read):** `fileName` here is `asset.name` from GitHub's release API response. GitHub's UI/CLI/API enforce that asset names cannot contain `/` or `\` — they're flat strings. Verified by inspection: asset names like `foo.tar.gz`, `linux-amd64`, never `foo/bar`.

**Trajectory:** **convergent** — sanitization is a no-op on the happy path. It would only matter if the GitHub API ever returned an asset name with separators (it doesn't), or if `fileName` ever sourced from user input directly (it doesn't here).

**Status:** **confirmed (low value).** Pure defense-in-depth. Not asked for. Reviewer reaction is unpredictable: some maintainers welcome it, some ask "what's the threat model?" and reject.

## H₄ — Stream resource cleanup is real but cosmetic

**Hypothesis:** Adding `.destroy()` on stream errors prevents a real fd leak, but the leak is unobservable because this is a one-shot GitHub Action — the process exits seconds after error.

**Perturbation (read):** `saveFile` is called from `downloadReleaseAssets`, which is called from `download`, which is called from `main.ts` at action entry. A stream error rejects the promise, which propagates up and exits the action. No long-running process; no accumulating fds.

**Trajectory:** **convergent.** Real bug, no observable consequences in the deployment context.

**Status:** **confirmed (low value).** Mergeable if isolated, but reviewer is unlikely to engage with "fix a leak in a process that exits in 5 seconds."

## H₅ — Frontier: does the new ConfigError test fail on master?

**Hypothesis:** The "Fail when no fileName, tarBall, or zipBall is specified" test is a fail-on-master/pass-on-fix gate — but only for the *new* error path the PR introduces.

**Perturbation:** Apply only the test diff to master, run `npm test`. Predicted: **the test fails on master** (master returns `[]`, doesn't throw). So it does fail-on-master in the literal sense, but the "bug" it documents was *invented by this PR*, not fixed by it. This violates the spirit of fail-on-master (catch an existing bug) while satisfying the letter.

**Trajectory:** **divergent against PR coherence.** A test that codifies your own behavior change isn't a regression test, it's a fixture for your refactor. Reviewer-readable as "what bug did this fix?"

**Status:** **confirmed.** Mode: deduction. Provenance check: matches the [[project_attest_gate_test_diff_apply]] sister verdict — this is a `no_tests_in_pr`-adjacent failure: there *is* a test, but the test only validates a change the PR itself introduced, not a pre-existing bug.

## Graph state

| Node | Status | Mode | Confidence |
|------|--------|------|------------|
| H₀ — PR scope vs issue ask | divergent against | deduction | 95% |
| H₁ — overscoped | confirmed | induction + deduction | 90% |
| H₂ — ConfigError = behavior change | confirmed | deduction | 95% |
| H₃ — path.basename ~no-op | confirmed (low value) | deduction | 85% |
| H₄ — stream cleanup ~cosmetic | confirmed (low value) | deduction | 85% |
| H₅ — test validates own change | confirmed | deduction | 90% |

## Recommendation

**Shrink PR #944 to docs-only.** Keep:
- `README.md` change
- `action.yml` description change
- The two glob tests (`{a,b}` brace expansion, `?` single-char) — they cover the docs claims, no risk

**Drop from this PR** (defer to issue-backed follow-ups, or close if not worth the trouble):
- `ConfigError` refactor in `resolveAssets` + its accompanying test — behavior change, no upstream issue
- `path.basename` sanitization — no threat model, no upstream issue
- Stream `.destroy()` cleanup — cosmetic in one-shot context, no upstream issue
- `unarchive.ts` try/finally — same shape, no upstream issue

**Rationale:** maintainer cadence is slow and review bandwidth is narrow. A 2-file docs-only PR closing a 14-month-old issue is plausibly merged in one pass. A 5-file PR with 4 unrequested concerns invites either "please split this up" (best case) or silent stall (likely case based on response pattern).

Per [[feedback_no_unrequested_features]] and the "imitate, do not reform" rule in the investigate skill — we contribute, we don't reform. The hygiene fixes are not wrong, they're just out of scope.

## Frontier (open)

- Should the dropped changes be opened as separate PRs at all? Depends on maintainer's appetite, which is currently unmeasured. Conservative move: ship the docs PR, see if it merges, *then* consider opening one tiny separate PR for the most defensible item (stream cleanup) as a probe.
- Is there an existing issue or comment from `robinraju` about path traversal, fd leaks, or input validation? Not seen in the 20 most recent commits or in #778; full issue tracker search would be the next perturbation if a follow-up PR is contemplated.

## Pruning log

- Killed: "the bundled hygiene fixes will be seen as a bonus." Maintainer history doesn't support this — they merge focused PRs only.
- Killed: "ConfigError is just a refactor." It changes thrown behavior; calls `path.basename` and stream destroy are similarly behavior-touching, not pure cleanup.

## Phase 8 — human gate

Not auto-shippable: PR already exists. Operator decisions needed:

1. Edit PR #944 in place — revert the four non-docs changes, force-push, update PR title/body to docs-only.
2. Or: leave as-is and accept the lower merge probability.
3. Or: close #944 and open a fresh, docs-only PR (cleaner history, loses thread continuity — none here yet since no review).

Recommend #1.
