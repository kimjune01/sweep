# Hypothesis Graph: robustmq/robustmq#1722

**Issue**: [Refactor] Implement cluster_config_set API for dynamic cluster configuration updates
**Filed**: 2026-02-09 by robustmq-project (maintainer org)
**State**: OPEN
**Verdict**: **STALE — already implemented upstream.** Halt, do not ship.

## H₀: The issue's premise still holds

- **Claim under test**: `cluster_config_set` in `src/admin-server/src/cluster/mod.rs` has empty/commented-out `FeatureType` branches and always returns `success`. `FeatureType` enum has the listed bugs (duplicate `SlowSubscribe`, missing `SystemAlarm`, wrong reference in `SlowSubscribe` branch).
- **Perturbation**: Read the current state of the named files at HEAD (commit `93dfbf3`, 2026-05-16).
- **Result**:
  - `src/admin-server/src/cluster/mod.rs` no longer contains `cluster_config_set` at all — it only has the `index` handler.
  - The handler lives at `src/admin-server/src/cluster/config.rs::cluster_config_set` and is fully implemented: string-matched dispatch on `ClusterDynamicConfig` variants (9 variants including `MqttSlowSubscribeConfig`, `MqttProtocol`, `MqttSchema`, `MqttSystemMonitor`, `MqttLimit`, `ClusterLimit`, `MetaRuntime`), calls `save_cluster_dynamic_config` + `update_cluster_dynamic_config`, returns proper error responses.
  - `src/common/base/src/enum_type/feature_type.rs` **does not exist** in the tree. `FeatureType` was removed entirely.
- **Trajectory**: **Divergent against H₀**. The bug described in the issue no longer exists in any form.
- **Shape**: Divergent.
- **Edge**: Investigate provenance — when and how was it fixed?

## H₁: Provenance — when did this land?

- **Perturbation**: `git log -S"cluster_config_set" --all` and follow-rename history of `src/admin-server/src/cluster/mod.rs`.
- **Result**:
  - Commit **`11f8662c`** ("refactor: Supports kafka protocol and amqp protocol parsing...", **PR #1820**), authored by **socutes** (a maintainer; same `So` as commits like #1873), merged **2026-03-24**, rewrote `cluster_config_set` to its current shape and removed `FeatureType` along with the commented-out branches.
  - The maintainer chose a different design than the issue proposed: instead of fixing `FeatureType` and adding 3 variants, they bypassed `FeatureType` entirely and dispatch on `ClusterDynamicConfig` variants directly.
  - An earlier community attempt, **PR #1724** by ShiLu1211 (referenced the issue, 2026-02-09), was **closed without merge on 2026-02-13** — superseded by the maintainer's own refactor 6 weeks later.
- **Confidence**: ~98% (deduction from git history).

## H₂: Should we open a "close this issue" PR or comment?

- **Perturbation**: Read the issue comments and check whether the maintainers noticed the supersedence.
- **Result**: Zero comments on #1722. Issue still OPEN. The maintainer who wrote #1820 (socutes) did not link or close it.
- **Trajectory**: Convergent — the issue is stale-open due to forgotten housekeeping, not because anything is needed in the codebase.
- **Action surface**: The only honest action is a short comment pointing out that #1820 resolved this, suggesting the maintainer close. **No code PR is justified** — there is nothing broken to fix.
- **Decision**: Do not ship a code PR. Optional: a single drive-by comment linking #1820 — but per /drip rules (one PR open per repo, value of unsolicited "please close this" comments is low), skip.

## Graph state

| Node | Hypothesis | Shape | Status |
|------|-----------|-------|--------|
| H₀ | Empty `FeatureType` branches still exist | Divergent against | Killed |
| H₁ | Fix landed via PR #1820 (`11f8662c`) | Divergent for | Confirmed |
| H₂ | Worth shipping a follow-up PR | Convergent (no) | Halt |

## Frontier

Closed. No open edges. Investigation halts at Phase 2.5 (provenance check killed the premise).

## Reasoning modes

- H₀: Deduction (read current files) → 98%.
- H₁: Deduction (git history + commit content) → 98%.
- H₂: Abduction → maintainer simply hasn't closed; no code action warranted → 85%.

## Pruning log

- H₀ killed by direct file read: `cluster_config_set` is implemented at a different path with a different design.
- The implied "implement the FeatureType-based dispatch" hypothesis died because `FeatureType` itself was deleted in #1820 — the maintainer chose dispatch-on-`ClusterDynamicConfig` instead.

## Halt

Issue is stale-open. The bug it describes has been gone since 2026-03-24 (PR #1820). No PR to draft.
