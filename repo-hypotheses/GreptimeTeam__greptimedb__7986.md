# GreptimeTeam/greptimedb#7986 — already fixed upstream

**Issue (2026-04-17, MichaelScofield):** When S3 delete fails inside the manifest checkpointer, the checkpoint file + `_last_checkpoint` aren't updated, causing long Datanode startup. Expected: delete failure should not hinder checkpoint update.

**Halt verdict (2026-05-18):** **Already fixed by PR #8001** (`fix: update manifest state before deleting delta files`), merged 2026-04-21 by maintainer evenyag. PR body links #7986 directly. Issue is still in `open` state because nobody closed it, but the code change is on `main`.

## H₀ — does main still exhibit the bug?

- **Perturbation:** read `src/mito2/src/manifest/checkpointer.rs` at HEAD (sha `9dd35e18`).
- **Observation:** `Inner::do_checkpoint` (lines 45-88) executes in this order:
  1. `save_checkpoint(version, &checkpoint).await` — error → return.
  2. `self.last_checkpoint_version.store(version, Ordering::Relaxed)` — advances in-memory pointer **as soon as the checkpoint file is durable**.
  3. `delete_until(version, true).await` — error → `warn!` only, function continues to `info!("Checkpoint for region {} success...")`.
- **Comment block lines 72-76** explicitly documents the invariant the issue asked for: "If the subsequent delta cleanup fails, the on-disk state is still consistent (the `_last_checkpoint` metadata points at the new checkpoint) and `maybe_do_checkpoint` must not re-checkpoint the same range."
- **Trajectory:** divergent against H₀. The bug is not present on `main`.
- **Mode:** deduction (read the code). Confidence: 98%.

## Provenance check

- `gh api repos/GreptimeTeam/greptimedb/commits?path=src/mito2/src/manifest/checkpointer.rs` — top commit `449243a1` (2026-04-21) is `fix: update manifest state before deleting delta files (#8001)`.
- PR #8001: author `evenyag` (maintainer), merged 2026-04-21T11:50Z, +178/-21 over 5 files, body explicitly links `https://github.com/GreptimeTeam/greptimedb/issues/7986` and says "Updating the manifest's checkpoint last version first. So a failed deletion won't leave an outdated last version."
- Issue #7986 state at investigation time: `open` (`closed_at: null`). The fix landed but the issue wasn't auto-closed (PR body used a bare URL, not a `Fixes #7986` keyword).

## Decision

- **Do not investigate further.** The frontier is closed: surviving hypothesis is "fix already shipped 4 days after issue filed."
- **Do not open a PR.** Nothing to add; maintainer already wrote and tested the fix with their own test coverage.
- **Do not post on the issue.** The maintainer (`evenyag`) is on the project and aware of the PR. A "by the way this is fixed" comment from an outside contributor adds noise without value; if the issue should be closed they'll close it.

## Graph state

| Node | Status | Shape | Edge |
|------|--------|-------|------|
| H₀: bug present on main | killed | divergent-against | none — fix exists |

Frontier: empty. Halt.
