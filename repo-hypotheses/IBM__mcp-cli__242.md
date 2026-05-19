# IBM/mcp-cli#242 — fix(ping): use transport-level health check for SSE servers

PR: https://github.com/IBM/mcp-cli/pull/242 (fixes #203)
Author: kimjune01 (us). State: OPEN, mergeable, 0 reviews/comments.
Question entering investigate: CI is red on all 16 test shards — is our fix broken, or is this a repo-wide gate?

## H₀ — Our diff broke the tests

- **Null:** Tests pass; failures are environmental/configurational.
- **Perturbation:** Read the failed-test log for `test (tests/adapters)` (job 75147370968 representative slice).
- **Result:**
  ```
  collected 133 items
  tests/adapters/test_*.py .................... [100%]
  ============================= 133 passed in 2.48s ==============================
  ERROR: Coverage failure: total of 12 is less than fail-under=60
  FAIL Required test coverage of 60.0% not reached. Total coverage: 11.51%
  ##[error]Process completed with exit code 1.
  ```
- **Trajectory shape:** Divergent against. Tests pass; the job fails because of a coverage threshold gate, not a test assertion.
- **Status:** KILLED.
- **Edge:** What's enforcing the 60% gate per-shard, and does it fail every PR?

## H₁ — Repo-wide CI gate fails every PR, not ours

- **Null:** Only our PR fails; main is green via some skipped path.
- **Perturbation:** `gh pr list ... --json statusCheckRollup` across the seven most-recent PRs (#233–#240, #242), plus `gh run list --branch main`.
- **Result:**
  - Every open PR (#236 pyasn1 bump, #238 download-artifact bump, #239 cryptography security bump, #240 upload-artifact bump, #242 ours) fails the same 16 test shards.
  - #234 ("Code stuff") was **merged** with the same 16 shard failures present on the PR.
  - Recent main runs are all `success` — but those are Dependabot metadata updates that don't trigger the test workflow, not the test workflow itself.
- **Trajectory shape:** Divergent for. 100% of PRs run through this CI configuration fail identically. The maintainer is already merging despite the red.
- **Status:** CONFIRMED.
- **Reasoning mode:** Induction (observed across population of PRs).
- **Confidence:** 95%.

## H₂ — The gate is per-shard `fail-under=60` against full `src/`

- **Null:** Coverage is aggregated across shards before the gate runs.
- **Perturbation:** Inspect CI invocation in the failing log.
- **Result:** Each shard runs `uv run pytest --cov=src --cov-report= tests/<shard>`. The `report-coverage` job (which would aggregate) is `SKIPPED` because upstream jobs fail. The `fail-under=60` threshold (set in `pyproject.toml`'s `[tool.coverage.report]`) fires per-shard. tests/adapters exercising 11% of `src/` is structurally expected — each shard covers its own slice.
- **Trajectory shape:** Divergent. The gate is incoherent as configured.
- **Status:** CONFIRMED.
- **Reasoning mode:** Deduction (read the invocation, traced the consequence).
- **Confidence:** 97%.

## Provenance check

- Not our regression — `git blame` on the CI config would show this gate predates branch `fix-203-sse-ping`. Confirmed indirectly by #233 (merged) and Dependabot PRs failing identically.
- Maintainer behavior reveals the truth: #234 merged with these failures. The red shards are treated as advisory, not blocking.
- DCO check is `ACTION_REQUIRED` on #242 — that *is* on us (missing `Signed-off-by` trailer). Separate concern from the test shards.

## Diagnosis

Two findings, only one of which we own:

1. **Test shards red (not ours).** Repo-wide pre-existing CI misconfiguration: per-shard coverage gate at 60% applied to full-`src/` coverage measured by a single shard. Structurally impossible to satisfy. Affects every PR including recently-merged #234. Not blocking — maintainer merges through it.
2. **DCO missing (ours).** `Signed-off-by` trailer absent on the commit. One-line fix: amend or rebase with `-s`.

## Frontier

- **Edge A (ship, do nothing on tests):** Land DCO sign-off; tests will stay "red" but maintainer's track record (#234) shows this isn't merge-blocking.
- **Edge B (helpful side-quest):** Open a separate small PR proposing aggregated coverage. Either drop `fail-under` from `pyproject.toml` and add it only to the `report-coverage` job, or run a single non-sharded coverage step. Out-of-scope for #242 — flag for triage / `/drip`, don't fold in here.
- **Edge C (review-side):** No reviewer feedback yet (0 reviews). When it arrives, re-enter the graph from that observation.

## Reasoning mode table

| Node | Mode | Confidence |
|------|------|------------|
| H₀ killed (tests pass) | Induction — read the log | 99% |
| H₁ repo-wide gate | Induction — observed across 7 PRs + 1 merge | 95% |
| H₂ per-shard gate against full src | Deduction — read invocation, traced consequence | 97% |
| DCO action required | Deduction — read check status | 99% |

## Action

No code change to #242 for the test shard failures. Two follow-ups:

1. Add DCO sign-off to the commit on `fix-203-sse-ping` (operator decision — `git commit --amend -s && git push --force-with-lease` requires explicit approval per project rules).
2. Optionally surface the CI coverage misconfiguration as a separate triage candidate.

Frontier closes here unless reviewer feedback arrives.

## Reinvestigation tick — 2026-05-18 (head SHA 2aebb9cf)

Re-entered after CI red. Same fingerprint as prior pass:

- 16 test shards FAIL with per-shard `fail-under=60` against full `src/` (H₂ confirmed again).
- `report-coverage` SKIPPED (upstream).
- **DCO now PASSES** — sign-off trailer already on the commit.
- `lint-and-typecheck` PASSES.
- No reviews / comments since last pass.

Diagnosis unchanged. Two consecutive iterations produced the same conclusion → **fixed point per halt condition.** No code change to push. The PR is mergeable as-is; the 16 reds are advisory per maintainer precedent (#234 merged through identical failures).

Action: none. Halt.

## Reinvestigation tick — 2026-05-19 (head SHA 2aebb9cf, unchanged)

Third pass. Same fingerprint:

- Failing-job log for `test (tests/adapters)` confirms `133 passed in 2.54s` followed by `Coverage failure: total of 12 is less than fail-under=60`.
- `gh run list --branch main --workflow ci.yml` shows main itself failing on every push event (Mar–May 2026); the "success" runs in the default `gh run list` view are Dependabot metadata PRs that never trigger the test matrix.
- `pyproject.toml` on main still carries `[tool.coverage.report] fail_under = 60`; the workflow's per-shard step invokes pytest-cov without overriding it, so the gate fires on each shard.
- PR's only diffs remain `src/mcp_cli/commands/servers/ping.py` (+20/-7) and `tests/commands/definitions/test_ping_command.py` (+139/-22). Neither file is in the failing shards' path; neither could plausibly cause the failures.

Three consecutive iterations, same diagnosis → **fixed point per halt condition**. No patch to push to `fix-203-sse-ping`. Operator: PR is mergeable on its substance; the 16 reds will not clear without a workflow change that is out-of-scope for this PR.
