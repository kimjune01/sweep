# cri-o/cri-o Triage Graph

Updated: 2026-05-09

## Repo Profile

- **Language:** Go
- **Domain:** Container runtime (CRI implementation for Kubernetes)
- **Org:** CNCF (Cloud Native Computing Foundation)
- **Maintainers:** @saschagrunert, @haircommander, @bitoku, @kwilczynski
- **CI:** OpenShift CI (Prow), requires `/ok-to-test` from org member
- **Review culture:** Maintainer-gated. Non-org PRs wait for `/ok-to-test` before CI runs. CodeRabbit auto-reviews. Stale bot closes after 90 days.

## Active PR

### fix/numeric-usernames → #9432
- **Issue:** [#9432](https://github.com/cri-o/cri-o/issues/9432) — Stop using fully numeric usernames
- **Branch:** `fix/numeric-usernames`
- **Commit:** `0f960f03c`
- **What:** `GeneratePasswd` and `GenerateGroup` write fully numeric usernames/group names into `/etc/passwd` and `/etc/group`. shadow-utils on Fedora/RHEL rejects these. Fix: `safeAccountName()` prefixes all-digit names with `"user"`.
- **Risk:** Behavioral change for containers using `runAsUser` with numeric UIDs. Maintainer @bitoku previously suggested a config option for soft landing. We went with unconditional fix (simpler, matches Podman behavior) — maintainer may request a gate.
- **Prior art:** PR #9446 by @R3hankhan123 used same approach, closed by stale bot without review. Issue assigned to @R3hankhan123 but inactive.
- **Tests:** 5 new Ginkgo tests: numeric passwd prefix, large numeric prefix, non-numeric passthrough, mixed alphanumeric passthrough, numeric group prefix.
- **Review status:** Not yet submitted as upstream PR. In drip queue.

## Assessed & Rejected

| Issue | Title | Reason |
|-------|-------|--------|
| #9934 | Bump held-back deps | @vishu-25 actively working, maintainer engaged |
| #9931 | UpdateRuntimeConfig | Assigned to @nispriha |
| #9902 | Multiple Accept headers | Maintainer said won't fix (RFC-compliant) |
| #9885 | exec newline s390x | Competing PR #9904 from @isumitsolanki |
| #9935 | pinns getopt_long | Competing PR from @cehoffman, maintainer approved |
| #7586 | SIGHUP config reload | Assigned to @LenkaSeg, actively working |
| #8541 | UNIX socket metrics | Assigned to @roman-kiselenko |
| #9856 | Corrupted image fetch | Regression, stale, needs CRI-O cluster to repro |

## Watch List (Re-triage Later)

| Issue | Title | Signal |
|-------|-------|--------|
| #9432 | Numeric usernames | Our PR — monitor for review |
| #9934 | Held-back deps | If @vishu-25 stalls, revisit |
| #9856 | Corrupted image | If maintainer confirms regression window |
| #9772 | VM runtime panic | Competing PR #9776 exists but no review |
| #9675 | Seccomp privileged | Competing PR #9775 exists but no review |
