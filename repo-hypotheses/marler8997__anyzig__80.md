# marler8997/anyzig#80 — anyzls Mach version resolution

**PR**: https://github.com/marler8997/anyzig/pull/80
**Issue**: #73 (anyzls 404s when given a Mach Zig version, e.g. `2024.11.0-mach`)
**Author**: kimjune01 (self-investigation; CI green; no maintainer review yet)
**Branch**: `fix-zls-mach-version`

## H₀ — baseline observation (induction)

Issue #73: `anyzls` on a `build.zig.zon` with `.minimum_zig_version = "2024.11.0-mach"` attempts to download `https://builds.zigtools.org/zls-x86_64-linux-2024.11.0-mach.tar.xz` → 404, because ZLS has no Mach-named build.

Confirmed: that URL is constructed in `getVersionUrl` (src/main.zig) by formatting the raw `semantic_version` into the ZLS path template, with no Mach branch.

**Trajectory**: divergent — the bug is real, reproducible from code reading.

## H₁ — PR #80 fix shape (deduction)

The PR adds `extractZigVersionFromMachIndex`: when `isMachVersion(v)` is true and we're building ZLS, fetch `pkg.hexops.org/zig/index.json`, look up the Mach version key, read its `version` field, and use *that* as the ZLS version string. Otherwise unchanged.

So `2024.11.0-mach` → index lookup → `0.14.0-dev.2577+271452d22` → URL `https://builds.zigtools.org/zls-x86_64-linux-0.14.0-dev.2577+271452d22.tar.xz`.

**Reasoning**: PR body says "Mach versions are not valid semver for ZLS compatibility checks; the fix maps them to their base Zig release version."

## H₂ — does the resolved URL exist? (induction — **kill**)

**Perturbation**: probe the resolved URL directly.

```
$ curl -sI https://builds.zigtools.org/zls-x86_64-linux-0.14.0-dev.2577+271452d22.tar.xz
HTTP/2 404
```

Probed ZLS's release surface:
- `https://builds.zigtools.org/index.json` lists only stable releases (`0.10.0`–`0.16.0`). No `dev` entries.
- `gh release list --repo zigtools/zls` confirms: only stable releases exist. ZLS does **not** publish per-dev-commit nightlies.
- Even the *stable* `zls-x86_64-linux-0.14.0.tar.xz` is 404; the actual URL is `zls-linux-x86_64-0.14.0.tar.xz` (os-arch, not arch-os). The existing `arch_os_swap_release` branch handles this — but only for `.release` kind, not `.dev`.

**Trajectory**: divergent against — the fix swaps one 404 for another 404 on the exact reported case.

The PR description says it maps Mach to "base Zig release version," but in fact it maps to the **underlying Zig dev commit**, which has no ZLS counterpart. To actually resolve the issue, the fix would need to strip `-dev.NNN+HASH` and use the bare `major.minor.patch` (e.g. `0.14.0`), letting the existing `arch_os_swap_release` logic pick the `os_arch` URL form.

**Kill condition**: end-to-end download still fails for `2024.11.0-mach` on Linux. CI did not catch this because anyzig's CI doesn't actually run `anyzls` against a Mach-pinned `build.zig.zon`.

## H₃ — edge: ZLS-Zig compatibility (abduction, open)

Even with the corrected mapping (`-mach` → `0.14.0` stable), Mach pins to a *dev* Zig version. ZLS 0.14.0 stable is built against Zig 0.14.0 stable. Running ZLS 0.14.0 against a dev Zig snapshot may have AST/std-lib drift surfaces. Frontier edge: does ZLS gracefully degrade or hard-crash?

**Open** — not investigated; orthogonal to whether the download URL resolves.

## H₄ — edge: cache staleness (deduction, low severity)

`extractZigVersionFromMachIndex` consults the on-disk `download-index-mach.json` first, fetches only on cache miss. If the cached index lacks the Mach key but a refetched one would have it, the cache-miss branch correctly re-fetches and re-extracts. If the index just doesn't list the version, `errExit` triggers with a clear message. No silent fallback to the original 404 URL.

**Status**: confirmed clean — the cache-then-refetch path is symmetric with `getVersionUrl`'s existing Mach handling.

## H₅ — edge: SemanticVersion lifetime (deduction)

`extractVersionFromMachIndex` has `defer root.deinit()` and returns `SemanticVersion.parse(zig_version_val.string)`. Checked the `SemanticVersion` impl (src/main.zig:689) — it uses `std.BoundedArray` with `@memcpy` from the source string into a fixed inline buffer. So the returned value is independent of `root`'s arena. No use-after-free.

**Status**: killed (no bug).

## H₆ — edge: PR body vs behavior divergence (deduction)

PR title and body claim the fix "resolves the underlying Zig version" — true literally, but the implication ("ZLS will then download successfully") doesn't follow because ZLS lacks dev builds. The PR description is honest about the mechanism but optimistic about the outcome.

## Graph state

| Node | Status | Shape | Mode |
|------|--------|-------|------|
| H₀ — original 404 reproducible | confirmed | divergent | induction (code-read) |
| H₁ — PR shape: resolve via mach index | confirmed (shape only) | divergent | deduction |
| H₂ — resolved URL exists | **killed** | divergent against | induction (curl probe) |
| H₃ — ZLS-Zig dev compat | open | — | abduction |
| H₄ — cache staleness | killed | — | deduction |
| H₅ — SemanticVersion lifetime | killed | — | deduction |
| H₆ — PR claim vs reality | confirmed | — | deduction |

## Diagnosis

The PR does not fix the reported bug end-to-end. It correctly identifies that Mach versions need resolution against the Mach download index, but resolves them to **dev** versions that ZLS doesn't publish. The user-visible behavior changes from "anyzls: downloading `...2024.11.0-mach.tar.xz`... 404" to "anyzls: downloading `...0.14.0-dev.2577+271452d22.tar.xz`... 404" — a different URL but the same failure.

## Frontier — what would actually fix #73

A two-step resolution:
1. Mach version (`2024.11.0-mach`) → underlying Zig version via index (already in PR).
2. Underlying Zig version → nearest **stable** ZLS release (strip `-dev.N+H`, e.g. `0.14.0-dev.2577+271452d22` → `0.14.0`).

That lets the existing `arch_os_swap_release` logic produce the correct `zls-linux-x86_64-0.14.0.tar.xz` URL. H₃ (compatibility) remains, but at least the binary resolves.

## Provenance

- Mach index probed live: `curl -s https://pkg.hexops.org/zig/index.json` confirmed `2024.11.0-mach.version == "0.14.0-dev.2577+271452d22"` on 2026-05-18.
- ZLS release inventory: `gh release list --repo zigtools/zls` and `https://builds.zigtools.org/index.json` — only stable releases.
- ZLS URL format check: `zls-x86_64-linux-0.14.0.tar.xz` → 404; `zls-linux-x86_64-0.14.0.tar.xz` → 200. Confirms `arch_os_swap_release` is necessary even for stable URLs in this version range.
- CI green is uninformative — anyzig's build CI compiles the binary; it doesn't run `anyzls` against a Mach zon.

## Recommended action

Do not merge as-is. Either:
- **(a) Revise the PR** to strip dev suffix before constructing the ZLS URL, and add an end-to-end test that asserts the resolved URL returns 200 (or at least, that the constructed string matches the stable ZLS URL pattern).
- **(b) Convert to draft** and use the find as evidence in a maintainer-facing comment ("the fix shape is wrong — here's what we measured"), letting the maintainer decide direction.

Option (b) matches the tissue / human-attendable pattern for a user-authored PR where the operator can revise before reviewer time is spent.

---

## Round 2 (2026-05-17): re-verification + stale-branch finding

Re-ran H₂'s probe today:

```
mach 2024.11.0 → zig 0.14.0-dev.2577+271452d22
zls-x86_64-linux-0.14.0-dev.2577+271452d22.tar.xz → 404   (what PR produces)
zls-x86_64-linux-0.14.0.tar.xz                    → 404
zls-linux-x86_64-0.14.0.tar.xz                    → 200   (what would actually work)
```

H₂ still holds: fix swaps one 404 for another.

### H₇ — build.zig hunk in PR diff (induction)

- **Perturbation:** `git diff master..fix-zls-mach-version -- build.zig`.
- **Result:** PR appears to delete the `HEW_BUILD_REVISION` env-var handling block from the anyzig (not anyzls) executable.
- **Provenance:** `git log master -S "HEW_BUILD_REVISION"` → commit `7aa484c` *"support HEW_BUILD_REVISION"* by Jonathan Marler, 2026-05-15. Branch was cut 2026-05-12, three days earlier. The deletion is an artifact of the branch being behind master; my branch never had this code.
- **Trajectory:** divergent — the hunk is real-but-unintended.
- **Shape:** divergent against. **Status: confirmed problem.**
- **Edge:** rebase or merge master before any further work — the maintainer is virtually guaranteed to notice his own commit being reverted, which compounds the H₂ correctness problem.

### Consolidated diagnosis

Two independent blockers on this PR:
1. **Correctness (H₂):** resolved URL still 404s for the reported case.
2. **Hygiene (H₇):** branch is 5 days stale; diff includes accidental revert of maintainer's `HEW_BUILD_REVISION` work.

Either alone is sufficient reason for the maintainer to bounce the PR. Together they explain the 5-day silence cleanly.

### Updated recommended action

The PR needs a real revision, not a rebase-and-amend:
1. **Rebase on master** to drop the spurious build.zig hunk (H₇).
2. **Fix the URL construction** so `0.14.0-dev.N+H` → stable `0.14.0` for the ZLS lookup (H₂). One approach: after resolving via the Mach index, run the result through a `stripDevSuffix` helper before passing to the existing `arch_os_swap_release` branch.
3. **Add a unit-level assertion** for the URL string — the repo's integration test for Mach is `continue`-skipped on infra outage, so a string-shape assertion is the only practical local check ([[project_attest_gate_test_diff_apply]] will still flag `no_tests_in_pr` for integration tests, but a unit test gives fail-on-master/pass-on-fix evidence).

This is now a Phase 8 human gate. The fix shape changed; this is not an amend, it's a re-implementation. Operator decides whether to revise PR #80 or close it and let /investigate produce a fresh attempt.

---

## Round 3 (2026-05-17): local-validation blocker — PR moved to draft

### H₈ — local build blocked by Zig version drift (induction)

- **Perturbation:** operator attempted to build the branch locally on Zig 0.16 to validate any revised fix.
- **Result:** `build.zig.zon` hash format rejected by Zig 0.16 — "invalid hash: incomplete". The zon file was authored against an older Zig; current toolchain requires the newer multihash format.
- **Trajectory:** divergent against — re-implementation (per Round 2 recommendation) cannot be locally fail-on-master / pass-on-fix attested without pinning a specific older Zig version, which the operator does not have set up cleanly.
- **Shape:** divergent against. **Status: confirmed environment blocker.**
- **Edge:** none locally. The PR was moved to draft with an honest maintainer-facing comment ([PR #80 comment, 2026-05-18T03:49Z](https://github.com/marler8997/anyzig/pull/80)) explaining the toolchain mismatch and yielding.

### Halt

Frontier closes for this investigation:
- H₂ (URL still 404s) — correctness blocker, requires re-implementation.
- H₇ (stale branch reverts maintainer commit) — hygiene blocker.
- H₈ (Zig 0.16 vs zon hash format) — operator cannot attest a revision locally.

No further code action. The graph document is the artifact; the draft comment is the maintainer-facing tissue. Investigation terminates at depth 3 (cycles, not phases) per the reframe rule — the surviving observation is "this PR cannot ship from this operator without setting up a pinned Zig toolchain," which is an environmental fact, not a frontier edge.

### Reasoning mode

| Node | Mode | Confidence |
|------|------|------------|
| H₈ — local build blocked | induction (operator-reported error) | 99% |
| Halt decision | deduction (three independent blockers, one environmental) | 95% |
