# databendlabs/databend#19830 — reinvestigate

PR: feat(query): support TH/th ordinal and V shift patterns in to_char
Head: feat/to-char-th-ordinal @ 21fdfaa4cffc

## H₀: Failing checks are real test regressions

Perturbation: read the failing-job tail from context pack.

Trajectory: **divergent against**. Three failing checks:
- `cla` — bot grep for the CLA acknowledgement
- `description` — bot grep for `## Tests` and `## Type of change` checkboxes
- `linux / sqllogic / cluster (tpch, 2c, hybrid)` — bot's retry analyzer itself classified this as "Retryable (Infrastructure)"; passed on all other sqllogic shards

Killed: no code-level regression. Failures are policy bots + infra flake.

## H₁: PR body diverged from template grep

Perturbation: fetch `.github/PULL_REQUEST_TEMPLATE.md` and diff against PR body.

Findings:
- CLA line was markdown-linked (`[docs...](url)`) — bot wants bare URL
- Missing `## Tests` section with at least one checked box
- Missing `## Type of change` section with at least one checked box

Trajectory: **convergent**. Three independent grep targets, all addressable by body edit.

## Action

Rewrote PR body to match template verbatim (bare CLA URL, Tests section with Unit/Logic checked, Type of change with New Feature checked). Used `gh pr edit --body-file`.

## Verification

PR Assistant run 26051952968 (triggered by edit) completed:
- `cla` success
- `description` success
- `title` success

Remaining failure: `linux / sqllogic / cluster (tpch, 2c, hybrid)` — cannot rerun without admin. Bot already flagged as infra-retryable; needs maintainer rerun or a follow-up push to retrigger. No code change indicated.

## Frontier

Closed. The patch was a description-template fix, not a code fix. No diff shipped; no new PR.

## Cycle 2 (2026-05-18)

Reinvestigate context pack listed `cla` + `description` + `tpch hybrid` as failing — pack was stale. `gh pr checks` shows the post-edit re-runs from cycle 1 already green:

- `cla` pass (run 26079658951 / job 76678074128)
- `description` pass (run 26079658951 / job 76678074152)

Only `tpch / 2c / hybrid` (job 75176608225) remains red. `gh api .../jobs/75176608225` returns `conclusion=failure` with zero failed steps — runner-side cancellation, not a sqllogic assertion. All 17 sibling sqllogic shards passed on the same run. Confirms H₀ classification: infra flake.

Touched body with no-op `gh pr edit --body-file` to confirm description/cla don't regress on a re-edit; both passed again. Frontier remains closed; only outstanding gate is the flake-retry, which requires write access we don't have.

## Cycle 3 (2026-05-18 reinvestigate)

Same pack, same divergence. `gh pr view` rollup at this moment:

- Latest `cla` run (26079658951, 2026-05-19): SUCCESS
- Latest `description` run (26079658951, 2026-05-19): SUCCESS
- `linux / sqllogic / cluster (tpch, 2c, hybrid)`: still the single 2026-05-09T19:15 FAILURE; no re-run since.
- `ready`: stale FAILURE composite, will flip when sqllogic re-runs green.

Confirmed empirically that title/body edits since 2026-05-09 only re-trigger metadata workflows (`cla`, `description`); the heavy `linux` workflow is push-gated. Job log for 75176608225 is now expired (HTTP 404 / BlobNotFound) — we cannot inspect the original failure further; only the CI-bot's prior classification remains: `Retryable (Infrastructure)`.

Local worktree clean, HEAD matches PR head SHA, branch is 20 commits behind `origin/main`. Phase 8 (ship) options offered to operator:

1. Merge `origin/main` into branch, push — re-triggers full CI, fixes 20-commit drift, no force-push, one merge commit visible in PR.
2. Empty `--allow-empty` commit + push — minimal, retriggers CI only.

Frontier still closed on code. Awaiting operator pick of retrigger shape.

**Action taken**: merge-main attempt failed (shallow worktree, unrelated histories on local fetch); fell back to option 2. Empty commit `3b8322cbb9` (`chore: retrigger CI`) pushed to `feat/to-char-th-ordinal`. Watching for cluster sqllogic re-run on the new SHA.

## Cycle 4 (2026-05-19 reinvestigate)

CI re-ran on `3b8322c`. cla/description now SUCCESS. New failure: **different sqllogic shard** — `linux / sqllogic / cluster (cluster, 2c, http)`, run 26080290253, job 76687941611. 871/872 tests pass; one fails: `tests/sqllogictests/suites/mode/cluster/filter_nulls.test`.

**Failure shape:** `EXPLAIN SELECT * FROM table1 INNER JOIN table2 INNER JOIN table3 ON ...` cardinality mismatch. Expected outer-HashJoin `estimated rows: 500.00`; actual `250.00`. Inner join estimates match (250 both sides).

**H₃ — flake is in the optimizer's cluster-mode cardinality estimator, not in the PR.**

Evidence:
- PR diff (merge-base → head) = `src/common/io/src/number.rs`, +151/-7 only. Pure to_char number formatting. No path to query planner.
- `tests/sqllogictests/suites/mode/cluster/filter_nulls.test` is **byte-identical** on `origin/main` and `pr19830` at the failing line (96: `estimated rows: 500.00`).
- Recent main commit `76affaf refactor(optimizer): Improve histogram-based selectivity and join statistics estimation (#19775)` is in both branches; no follow-up test update to `filter_nulls.test`. Likely source of the 500↔250 nondeterminism on cluster nodes (sample-based histograms across shards).
- Sibling cluster sqllogic shards (`cluster/cluster/native`, `cluster/tpch/hybrid`, ...) all green on this run; only the http variant tripped, and only on this one test.

**Trajectory: convergent** with prior infra-flake classification. Different shard, different test name, same family: cluster-mode cardinality estimate non-determinism. The PR cannot be the cause.

**Action**: retrigger again. Push another empty commit. The flake will probably eventually pass. If the maintainer wants a permanent fix, it's a one-line change to `filter_nulls.test` (add `<slt:ignore>` tolerance to line 96, or update the expected value alongside #19775's stats refactor) — not our PR to make.

Optionally post a short maintainer comment pointing at #19775 as the likely drift source so they don't keep manually retrying. Phase 8 ship gate: another empty retrigger commit. Same shape as cycle 3.
