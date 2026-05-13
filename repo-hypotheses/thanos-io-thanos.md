# Triage Graph: thanos-io/thanos

**Date:** 2026-05-09
**Repo:** https://github.com/thanos-io/thanos
**Category:** CNCF project (Prometheus HA), Go + React

## Repo Health

- Daily external merges: yes
- Active maintainers: GiedriusS (MEMBER), fpetkovski (CONTRIBUTOR), saswatamcode, yeya24
- Good-first-issue count: 10 open
- Adjacent to: prometheus (already in roster)

## Issues Scanned

### #8506 -- bucketweb labels for status row always visible [SELECTED]
- **Labels:** good first issue, component: bucket tools
- **Competing PRs:** #8612 (Dec 2025, dead -- 5 months, 0 reviews, 0 comments, only package-lock noise + minor helper change)
- **Maintainer engagement:** Low (issue filed, labeled, no design guidance)
- **Acceptance criteria:** Labels visible on each source row without clicking block details
- **Effort:** Small (3 files, React component + CSS + test)
- **Branch:** `fix-8506-bucketweb-labels-visible`
- **Status:** Committed, tests pass (255/255)

### #8093 -- CapNProto gets initialised even though I'm using protobuf [DEFERRED]
- **Labels:** bug, good first issue, component: receive
- **Competing PRs:** #8616 (Dec 2025, stale since Jan -- reviewer raised backward-compat concern)
- **Maintainer engagement:** Good (member filed, contributor reviewed)
- **Assessment:** Design disagreement between member (wiardvanrij) and contributor (fpetkovski). The dual-server architecture is intentional for rolling protocol upgrades. Fix requires careful design that doesn't break existing deployments. Not suitable for a first PR -- needs maintainer alignment.

### #8794 -- Rule: Support native --rule-file auto-reload [SKIP]
- **Competing PRs:** #8804 (May 4 2026, actively being worked by yosshi825 with maintainer guidance)
- **Assessment:** Taken, actively in progress.

### #8103 -- Use the new os.Root type [SKIP]
- **Competing PRs:** #8797 (Apr 30 2026, actively being worked by guidonguido)
- **Assessment:** Taken, actively in progress.

### #8361 -- thanos store fails on Windows MinIO paths [SKIP]
- **Competing PRs:** #8613 (Dec 2025, stale, 0 reviews)
- **Assessment:** Windows-specific, hard to test without Windows CI. Low priority.

### #7905 -- QFE should expose httpgrpc through gRPC [SKIP]
- **Competing PRs:** None
- **Assessment:** Zero competing PRs but complex architecture (httpgrpc translation layer). Multiple claimers failed over 18 months. No maintainer guidance. Not a first-PR target.

### #8114 -- Flaky TestReloader_ConfigDirApplyBasedOnWatchInterval [SKIP]
- **Competing PRs:** #8395, #8500 (both stale, no reviews)
- **Assessment:** Flaky test fix with race condition. Two failed attempts already.

### #8115 -- Flaky TestCompactWithStoreGateway [SKIP]
- **Competing PRs:** #8393 (stale)
- **Assessment:** Flaky test, low maintainer engagement.

### #7066 -- UI: Warnings when building react app [SKIP]
- **Assessment:** Old (2023), likely outdated. Low value.

### #6889 -- docs: link paths differ on 'tip' vs 'v0.xx' [SKIP]
- **Assessment:** Old (2023), partially fixed by #6927. Hugo config issue.

## Decision

**Primary:** #8506 (bucketweb labels). Dead competing PR, clear acceptance criteria, clean React fix.

**Pipeline position:** Bug fix PR (our first). Follows the "bug fixes merge, features don't" heuristic for cold repos.

## Next Steps

1. Push branch, open PR via drip queue
2. If merged: look at #8093 (capnproto) once maintainer design alignment is clear
3. If merged x2: graduate to feature PRs (e.g., #7905 QFE httpgrpc)
