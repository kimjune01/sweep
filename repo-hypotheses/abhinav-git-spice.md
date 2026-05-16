# Triage Graph: abhinav/git-spice

## MAINTAINER PREFERENCES

- **Target branch**: main
- **Commit limits**: No explicit limit. "All commits must include meaningful commit messages."
- **CLA**: None specified.
- **PR template**: No mandatory template.
- **Changelog**: User-facing changes require `mise run changie new`. Non-user-facing changes need `[skip changelog]: reason` in PR description.
- **Test convention**: testscript-based (go-internal/testscript), files in `testdata/script/`. Unit tests use `go.uber.org/mock/gomock`.
- **Code style**: Effective Go + Uber Go Style Guide. Semantic line breaks in docs/comments.
- **Review style**: Active, solo maintainer (@abhinav). Responds to issues/PRs within days. Prefers discussion before significant features. Bug fixes with tests are well-received.
- **Build system**: mise for task management. `mise run build/lint/test`.

## ISSUE SCORES (Session 2)

### Attempted

| # | Title | Score | Status | Branch |
|---|-------|-------|--------|--------|
| 1134 | repo sync: do not restack after merge without --restack | 10 | dripped (prior session) | fix-repo-sync-no-restack |
| 659 | repo sync left repo in broken state with concurrent write | 8 | triaged | fix-head-lock-retry |
| 314 | restack: Detect merges | 7 | triaged | fix-restack-detect-merges |
| 966 | Duplicate GitHub Actions runs when updating stacked PRs | 6 | triaged | fix-submit-event-ordering |

### Deferred

| # | Title | Reason |
|---|-------|--------|
| 1135 | repo sync: --restack scope is incorrect | Enhancement, needs design discussion per maintainer. "Bug fixes only" rule for first contribution. |
| 1039 | Repo restack autostash fails | Can't reproduce without reporter's specific env (fsmonitor, git config). No maintainer response. |
| 1050 | Support for forgejo / codeberg forge | Feature, not a bug fix. Large scope. |
| 1047 | Support for Azure DevOps as a forge | Feature, not a bug fix. Large scope. |
| 947 | gs ls is slow | Performance issue. Maintainer says "I have some ideas" — wants to own the approach. |
| 1002 | support git switch | Enhancement, needs design discussion. |

### Denied

| # | Title | Reason |
|---|-------|--------|
| 1134 | repo sync: do not restack after merge without --restack | Already triaged and dripped in prior session |

## FIX DETAILS

### #659: fix-head-lock-retry

**Root cause**: Lock retry mechanism only detected "index.lock" in stderr, missing "HEAD.lock" errors that occur during concurrent git operations (e.g., repo sync rebase running alongside another git process).

**Fix**: Generalized `indexLockObserver` to `lockObserver` that matches both "index.lock" and "HEAD.lock" tokens. Extended rebase retry path to wait for either lock file to clear.

**Files changed**:
- `internal/git/index_lock_retry.go`: New `lockObserver` type with multi-token matching, backward-compat aliases
- `internal/git/index_lock_retry_test.go`: Tests for HEAD.lock detection, boundary matching, retry behavior
- `internal/git/rebase_wt.go`: Check both index.lock and HEAD.lock paths in retry loop

### #314: fix-restack-detect-merges

**Root cause**: When a branch was merged into its base (e.g., via GitHub merge commit), `gs stack restack` tried to rebase already-merged commits, causing conflicts or duplicates. The restack code didn't check for merged state.

**Fix**: Added merge detection in `spice.Restack()`: if the branch HEAD is reachable from the base HEAD (`IsAncestor`), the branch was merged. Returns new `BranchMergedError`. Restack handler catches this and warns user to run `gs repo sync`.

**Files changed**:
- `internal/spice/restack.go`: New `BranchMergedError` type, merge check before rebase
- `internal/handler/restack/handler.go`: Handle `BranchMergedError` with warning
- `testdata/script/stack_restack_merged_branch.txt`: Regression test

### #966: fix-submit-event-ordering

**Root cause**: When updating existing PRs, git-spice pushed the branch first, then called EditChange to update base/metadata. This generated two webhook events (synchronize + edited) nearly simultaneously, causing duplicate GitHub Actions runs.

**Fix**: Reordered operations: EditChange (base/metadata) first, then push. EditChange triggers an "edited" event (not listened to by default CI), then push triggers a single "synchronize" event with the correct base.

**Files changed**:
- `internal/handler/submit/handler.go`: Moved EditChange block before push block in existing-PR update path
