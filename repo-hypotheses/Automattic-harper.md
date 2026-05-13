# Automattic/harper PR #3336 — ThereOwn linter false-positive investigation

PR: https://github.com/Automattic/harper/pull/3336
Branch: `kimjune01:fix/there-own`
Reviewer: @hippietrail (CHANGES_REQUESTED 2026-05-12T16:14Z)
Issue ref: https://github.com/Automattic/harper/issues/3276

## Hypothesis graph

| Node | Hypothesis | Mode | Perturbation | Trajectory | Status | Edge |
|------|-----------|------|--------------|------------|--------|------|
| H0 | Reviewer's claim references the PR's *current* HEAD code | Deduction | `gh api .../reviews` + commit log compare | Divergent against — comment posted 2026-05-12 16:13Z, fix commits landed 2026-05-13 01:31Z & 04:49Z **after** the review | killed | follow to H1 vs original commit |
| H1 | ThereOwn linter false-positives on "people there own nice cars" (reviewer's verbatim example) on **original commit e2309e58** | Induction | `git checkout e2309e58 -- there_own.rs`; read code | Divergent confirmed — original `match_to_lint` had no context guard; would lint any "there own" pair | confirmed for original | follow to H2 |
| H2 | Current HEAD (commit 8e799890) still false-positives on hippietrail's example | Induction | `cargo test does_not_flag_verb_own_after_noun` + harper-cli probe `"People there own expensive cars."` | Divergent against — test passes; harper-cli reports "No lints found" | falsified | follow to H3 |
| H3 | The fix on HEAD also covers issue #3276's other listed positive examples | Induction | Add 4 new tests pulled verbatim from #3276 (customise default lvl, modules c files, scripts create connection, silent appstore updates) + 2 they're own examples | Divergent confirmed — all 6 added positive cases lint correctly | confirmed | follow to H4 |
| H4 | Sentence-initial "There own X" (no preceding word) still gets caught (no guard regression) | Deduction | `preceded_by_word` returns false when there is no preceding token; `is_nominal()` check short-circuits | Divergent confirmed — added test `sentence_initial_there_own_still_flagged` passes | confirmed | frontier closed |
| H5 | The fix introduces collateral damage elsewhere in harper-core | Induction | Full `cargo test -p harper-core --lib` | Convergent — 5309 passed, 0 failed, 264 ignored (unchanged) | killed | frontier closed |
| H6 | PR meets AGENTS.md's "≥15 tests for new rules" rule | Deduction | Read AGENTS.md §"On Writing New Rules"; count tests | Originally 8 (under), now 16 (over) after expansion | confirmed | frontier closed |

## Provenance

- `harper-core/src/linting/there_own.rs:46` — guard `if template.eq_str("there") && preceded_by_word(ctx, |pw| pw.kind.is_nominal()) { return None; }` introduced in commit 8e799890 (2026-05-13 04:49Z) **after** hippietrail's review (2026-05-12 16:13Z).
- `match_to_lint_with_context` (replacing `match_to_lint`) is the API path that exposes surrounding token context, used elsewhere in harper-core for the same kind of disambiguation.
- `is_nominal()` defined at `harper-core/src/dict_word_metadata.rs:572` as `is_noun() || is_pronoun()`.

## Causal chain

The reviewer's comment is correct as of when it was written; it predates the two fix commits on the branch. The current HEAD already implements the exact disambiguation the reviewer asked for, and harper-cli end-to-end on the verbatim example produces no lint. The investigation therefore **does not produce a code change to address H1** — the code change already exists. What the investigation adds is **evidence the fix actually works**: 8 new tests covering hippietrail's example, the four issue #3276 positive cases for "there own", two for "they're own", a sentence-initial true positive, plus the existing 8.

## Reframe

The actionable output is not a fix, it's **evidence that the existing fix already addresses the review**, plus tests that document the coverage. The reviewer can verify in a single `cargo test there_own` run.

## Reasoning mode summary

- H0, H4, H6: Deduction (read code/comment timestamps/policy text) — high confidence
- H1, H2, H3, H5: Induction (ran tests / harper-cli) — high confidence

## Frontier

Closed. Open question that doesn't block: should the guard also handle "they're / theyre" preceded by a verb like "are" (e.g., "*they are theyre own command*" from issue #3276)? Current behavior treats those as always-positive, which is consistent with the reviewer's framing ("*they're own*" is "always a possessive error before own"). Tests `issue_3276_theyre_own_command` and `issue_3276_theyre_own_library` cover this and pass.
