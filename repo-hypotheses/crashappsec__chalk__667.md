# crashappsec/chalk#667 — Hypothesis Graph

**Issue:** [#652](https://github.com/crashappsec/chalk/issues/652) — `chalk dump` shows multiple `use` entries concatenated without separator.
**PR:** [#667](https://github.com/crashappsec/chalk/pull/667) — branch `fix/chalk-dump-formatting`, status: OPEN, CI: pre-commit SUCCESS, no reviews.
**Author observed bug:**
```
use run_sbom from "https://chalkdust.io"use embed_sbom from "https://chalkdust.io"
```

## H₀ — Baseline observation

The maintainer's reproducer runs `./chalk dump` and gets two `use` statements concatenated with no separator. `chalk dump` outputs `getConfig()` (`src/commands/cmd_dump.nim:25`), which reads `configKey` from `selfChalk`. The only writer to that key on the load path is `handleConfigLoad` (`src/selfextract.nim:560`).

- **Mode:** induction (read the reporter's terminal capture)
- **Trajectory:** divergent — bug clearly exists in some flow that produces `configKey`.

## H₁ — The fix in PR #667 patches handleConfigLoad's empty-string branch

**Claim:** prepending `"\n"` to `newEmbedded` when it was empty was producing the leading newline that got collapsed and lost separation on subsequent loads.

**Pre-fix (main, `selfextract.nim:471`):**
```nim
withUse = if useLine in lines: newEmbedded
          else: newEmbedded & "\n" & useLine
newEmbedded = withUse.strip()
```

**Post-fix (PR head):**
```nim
withUse = if useLine in lines: newEmbedded
          else:
            if newEmbedded.len == 0: useLine
            else: newEmbedded & "\n" & useLine
newEmbedded = withUse.strip()
```

**Perturbation (deductive trace, no execution):** simulate two sequential `chalk load` invocations.

| step | newEmbedded in | useLine | withUse (pre-fix) | after strip() | withUse (post-fix) | after strip() |
|------|----------------|---------|--------------------|---------------|----------------------|---------------|
| 1 | `""` | `use A` | `"\nuse A"` | `"use A"` | `"use A"` | `"use A"` |
| 2 | `"use A"` | `use B` | `"use A\nuse B"` | `"use A\nuse B"` | `"use A\nuse B"` | `"use A\nuse B"` |

**Classification:** *divergent against H₁*. The pre-fix and post-fix produce **byte-identical output** on both steps. `Nim`'s `strip()` is leading/trailing-only — interior newlines survive — and the only artifact removed in step 1 was a single leading `\n` that didn't affect downstream concatenation. The fix as written is a behavioural no-op for the path the maintainer reproduced.

- **Mode:** deduction
- **Confidence:** 95% (the trace is short and the language semantics are explicit)
- **Kill condition for H₁:** trace shows behavioural equivalence pre/post.

## H₂ — The bug lives in a different writer, not handleConfigLoad

Generated as the surviving edge from H₁'s kill.

**Claim:** the concatenation happens somewhere outside the `handleConfigLoad` newline branch — candidates:
1. `loadComponentFromUrl` (called at `selfextract.nim:449`) builds the embedded source from sub-components in a way that drops separators.
2. The "memoize" / cache writes a re-serialised config string that re-joins components without newlines.
3. `chalk dump` renders `code(getConfig())` (`cmd_dump.nim:27`) which is a `Rope` formatter (`$code(...)`) — `Rope` rendering may collapse adjacent code blocks.

**Open frontier — perturbations not yet run:**

- F1. Build the binary, run the maintainer's exact reproducer, dump the stored `configKey` value via a debug print (or `chalk dump.all`) before pretty rendering — does the raw stored string already lack the newline, or does it lose it during render?
- F2. Read `Rope`/`code` rendering — search for places that strip newlines from code blocks. If render-side, the fix should be in `cmd_dump.nim`, not `selfextract.nim`.
- F3. Compare with `chalk dump.all` (JSON form, `runCmdConfDumpAll`) — if JSON shows proper newlines but `chalk dump` does not, the issue is in `$code(...)`.

**Classification:** *frontier open*. F1 is decisive and cheap; ran out of cycle before executing.

## H₃ — The added test passes regardless of the source-code fix

**Claim:** `test_dump_multiple_use_statements_formatting` (`tests/functional/test_dump_formatting.py`) loads one c4m (`valid_1.c4m`) with four inline `use` lines via `--use-embedded-config`. The c4m source already has its own newlines on disk; whatever code path embeds it preserves them as bytes. The test therefore exercises a path that was *already working* — not the path the issue reports.

**Perturbation (not run):** `git stash` the `selfextract.nim` change, keep only the test, run pytest. Predicted classification: *convergent* — test passes on master. If confirmed, the test is not load-bearing for the fix.

- **Mode:** abduction
- **Confidence:** 65%
- **Why it matters:** memory `project_fail_on_main_origin` — tests must fail on main and pass with fix. If H₃ holds, this PR ships a test that proves nothing, which is the exact failure mode previously called out by a chalk reviewer.

## H₄ — Unrelated change: getParams loses its `ignore` parameter — **RESOLVED (2026-05-18 re-check)**

Original concern (earlier cycle): the diff also dropped `ignore = @[component.url]` from `getParams`, silently weakening validation. Re-checking `gh pr diff 667` on 2026-05-18: the current PR head touches **only** the formatting branch in `handleConfigLoad` and adds the new test. No `getParams` change present. Either the prior observation was on an earlier diff that has since been amended, or it was misread. Marking the node closed.

- **Status:** killed-by-recheck.

## Graph state

| node | status | trajectory | mode |
|------|--------|------------|------|
| H₀ | confirmed | divergent | induction |
| H₁ | **killed** | divergent against | deduction |
| H₂ | open frontier | — | abduction |
| H₃ | open frontier (predicted convergent) | — | abduction |
| H₄ | killed-by-recheck (no longer in diff) | — | deduction |

## Frontier edges

1. **F1 — raw configKey inspection** (predicted divergent, decisive): instrument the binary to print the raw `configKey` after the two-load reproducer. Tells us whether the bug is at write-time or render-time.
2. **F2 — Rope/code render audit** (predicted oscillatory): if F1 shows correct bytes, search `nimutils` / chalk's `Rope` rendering for whitespace collapsing in `code(...)`.
3. **F3 — test counterfactual** (predicted convergent): run the new test against `main` with no source patch. If it passes, H₃ confirmed and the PR's test claim is empty.

## Recommendation

**Before this PR ships further:**

1. Run F3 — confirm whether the test actually fails on main. If it passes on main, the PR is currently a no-op test plus a scope-creep params change. This is the cheapest gate.
2. If F3 confirms the test is empty, run F1 to locate the real bug. Either fix that bug in this PR (and rewrite the test to exercise it) or close this PR and reopen against the correct surface.
3. Decide on H₄: revert the `getParams` change to keep PR scoped to formatting, or split it out with its own rationale. Maintainers reading a "fix newline" PR will be confused by the validation-weakening change.

**Why this matters now:** the PR is open without reviews. Catching a no-op-test + scope-creep combo before the maintainer does preserves credibility. Better to amend (memory: `feedback_amend_is_low_risk`) than have the reviewer point it out.

## Re-entry log

- 2026-05-18 (cycle 2): re-investigated on operator invocation. Re-traced H₁ independently and reached the same deductive kill (Nim `strip()` makes pre-fix and post-fix byte-identical). Re-checked PR diff — H₄ no longer present, marked killed-by-recheck. Live concern remains H₃: the new test likely passes on master, which would make the attestation gate fail the PR. No new PR action (idempotency); recommend running attest before any merge nudge.

## Provenance

- Investigation date: 2026-05-18
- Tools: deductive trace only (no binary build, no test execution this cycle)
- Codex / Gemini volley: not run this cycle (deductive trace was decisive on H₁; reserve volley budget for F1 results)
- Worktree: `~/.sweep/worktrees/crashappsec__chalk/` at `fa3c863`
