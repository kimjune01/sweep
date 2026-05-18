# feldera/feldera PR #6219 — DeltaTestLocation helper overlap with #6042

PR: https://github.com/feldera/feldera/pull/6219
Branch: `kimjune01:fix-delta-test-location-methods`
Reviewer: @swanandx (COMMENTED 2026-05-13T13:50Z), @gz pinged
Issue ref: https://github.com/feldera/feldera/issues/6135
Competing: https://github.com/feldera/feldera/pull/6042 (`send_snapshot and reset API`, +2953/-1234, OPEN)

## Hypothesis graph

| Node | Hypothesis | Mode | Perturbation | Trajectory | Status | Edge |
|------|-----------|------|--------------|------------|--------|------|
| H1 | Independent: ours and #6042 target different domains, no class-level overlap | Deduction | Compare PR titles + issue refs (#6135 vs #5980) and file lists | Convergent against — both modify `python/tests/utils.py`, both extend `DeltaTestLocation` class | falsified | follow to H3 |
| H2 | Subset: #6042 already adds the exact methods ours adds (`read_table`, `log_files`) | Induction | `gh api .../pulls/6042/files \| grep -E "(read_table\|log_files)"` | Divergent against — #6042 adds `read_rows`, `log_json_paths`, `_s3_filesystem`, `_read_text`, `_read_parquet`; does NOT add our exact `read_table` or `log_files` names | falsified | follow to H3 |
| H3 | Partial overlap: same class, complementary purposes, no exact-method conflict | Induction | Diff method signatures and return types | Convergent confirmed — #6042's `read_rows()` returns `list[dict]` with `__feldera_*` cols stripped (test-row shape); ours `read_table()` returns `pyarrow.Table` (analytical shape). #6042's `log_json_paths()` lists transaction logs; ours `log_files()` lists data file URIs from current snapshot | confirmed | follow to H4 |
| H4 | Strict superset: ours subsumes everything #6042 adds | Deduction | Compare diff sizes and method counts (148 lines / 2 methods vs 2953 lines / 5+ methods on this class) | Killed — implausible by ratio | killed | frontier closed |
| H5 | The two PRs will produce a merge conflict in `python/tests/utils.py` regardless of merge order | Deduction | Both insert methods into `DeltaTestLocation` near `row_count` (#6042 inserts at line 121-216 area; ours inserts methods around `row_count` too) | Convergent confirmed — file-level conflict guaranteed; resolution is mechanical (interleave method definitions) | **falsified post-merge** | see H7 |
| H6 | Maintainer preference is to land #6042 first (larger feature, longer in flight, listed first in swanandx comment) | Induction | #6042 opened earlier, larger scope, swanandx framed comparison as "PR #6042 also adds similar functionalities" putting it first | confirmed — #6042 merged 2026-05-14T21:02Z | confirmed | frontier closed |
| H7 | After #6042 merged, our branch will textually conflict and need a rebase | Deduction | `gh pr view 6219 --json mergeable` post-#6042-merge | Divergent against — `mergeable: MERGEABLE`. #6042 inserted its new methods *before* `row_count` (lines 124-216); ours inserts *after* `row_count`. Different anchor regions → git three-way merge handled it cleanly | killed | frontier closed |
| H8 | `mergeStateStatus: BLOCKED` indicates something other than textual conflict blocking merge | Induction | 2 LGTM approvals (mythical-fred NONE × 2), CI green, reviewDecision `REVIEW_REQUIRED`, no MEMBER approval (swanandx COMMENTED, @gz silent) | Convergent — block is "no MEMBER approval yet", not conflict or CI | confirmed | frontier closed — waiting on @gz or @swanandx to approve |

## Provenance

- `python/tests/utils.py` in #6042 (commit visible via `gh api repos/feldera/feldera/pulls/6042/files`): adds `_s3_filesystem`, `log_json_paths`, `_read_text`, `_read_parquet`, `read_rows` methods to `DeltaTestLocation` between lines 121-216
- `python/tests/utils.py` in #6219 (our PR): adds `read_table`, `log_files` methods, both with `missing_ok` parameter, both using deferred imports matching the existing `row_count` pattern
- Issue #6135 (ours) is about test-helper ergonomics for Delta verification
- Issue #5980 (#6042's) is about output connector snapshot delivery — a feature, not a test-helper request

## Causal chain

#6042 incidentally extends the same test-helper class because its feature requires test infrastructure for snapshot mode. Our PR extends the same class because issue #6135 explicitly asked for these helpers. The intent overlap (read Delta tables in tests) produces complementary APIs (row-shape vs table-shape, transaction-log paths vs data-file paths). Neither subsumes the other; both can land if the conflict resolution is done thoughtfully.

## Reframe

The right call is not "ours vs theirs" — it's **which scope split do the maintainers want**. Three viable orderings:

1. **Land #6042 first, rebase ours**: minimal-diff path; we keep our two methods, drop nothing. Conflict resolution interleaves method definitions in `DeltaTestLocation`.
2. **Close ours, reopen our methods as a follow-up after #6042 lands**: highest-confidence path if the maintainers want a single integrated PR for the test-helper expansion.
3. **Coordinate with @gz to fold our two methods into #6042**: lowest total diff count, but couples our timeline to #6042's review cycle.

Our preference is (1) — minimal coupling, both contributors keep credit, #6135 stays cleanly resolved. But (2) is also acceptable since issue #6135 doesn't demand a particular PR.

## Reasoning mode summary

- H1, H2, H4: Deduction (file diffs, sizes) — high confidence
- H3, H5, H6: Induction (signature comparison, framing inference) — high confidence

## Frontier

Closed. As of 2026-05-18:

- #6042 merged 2026-05-14 (resolves scope-split — path 1 from Reframe was the implicit maintainer choice)
- Our PR is still `MERGEABLE` (no rebase needed; H5's predicted conflict was falsified — different anchor regions in the same class)
- `mergeStateStatus: BLOCKED` reflects "no MEMBER approval" rather than CI/conflict
- 2 non-MEMBER LGTM approvals on file; @gz pinged 2026-05-14, no reply in 4 days

Next perturbation if/when ground state changes: maintainer comment, request for changes, or staleness signal. No code work to do.
