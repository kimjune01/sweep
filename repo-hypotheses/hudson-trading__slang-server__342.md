# Hypothesis graph: hudson-trading/slang-server#342 (reinvestigate-from-attest)

## Context

PR #342 fixes hover markdown rendering for SystemVerilog backticks. All 9 remote CI
checks green, mergeable, no review yet. Attest gate flagged `test_fails_on_fix` with
payload: "Unable to find executable: build/bin/server_unittests — Errors while running
CTest".

## H₀ — attest reports the fix breaks tests

**Null**: tests pass on the fix branch.
**Perturbation**: run `ctest --test-dir build --output-on-failure` on the fix worktree.
**Result**: ctest immediately fails because `server_unittests` binary doesn't exist in
`build/bin/` — the bin directory is empty.
**Trajectory**: divergent (deterministic, reproducible).
**Shape**: divergent against H₀ as stated. The *test phase* didn't fail — the build
never produced an executable for it to run.
**Edge**: investigate why the binary is missing.

## H₁ — build was never run

**Perturbation**: `cmake --build build` on fix worktree.
**Result**: build fails. Multiple test source files (`HasValidBuffersTests.cpp`,
`HierarchyTests.cpp`, etc.) fail with:
```
GoldenTest.h:32: error: member access into incomplete type 'IResultCapture'
note: forward declaration of 'Catch::IResultCapture'
```
**Trajectory**: divergent.
**Shape**: confirmed — binary missing because build fails.
**Kill condition for H₁**: false start — *this is the new H₀*.

## H₂ — fix branch broke `GoldenTest.h`

**Perturbation**: `git diff main...HEAD -- tests/cpp/utils/GoldenTest.h`.
**Result**: empty. Fix branch doesn't touch GoldenTest.h.
**Perturbation 2**: read GoldenTest.h on `main` directly.
**Result**: same broken include layout — only `<catch2/internal/catch_context.hpp>`
(which forward-declares IResultCapture), no `<catch2/interfaces/catch_interfaces_capture.hpp>`.
**Trajectory**: divergent against H₂.
**Shape**: killed. The fault exists on main and is not caused by #342.
**Edge**: why doesn't this break CI?

## H₃ — local Catch2 (homebrew) is stricter than CI's bundled Catch2

**Perturbation**: check homebrew Catch2 headers at `/opt/homebrew/include/catch2/`.
**Result**: homebrew supplies `interfaces/catch_interfaces_capture.hpp` as the full
definition site; `internal/catch_context.hpp` only forward-declares `IResultCapture`.
A newer Catch2 release tightened the boundary — calling `getResultCapture()->method()`
now requires the interfaces header. CI passes because the project's test_setup
bootstraps a vendored Catch2 (likely older, where context.hpp transitively included
the full type) via submodules.
**Trajectory**: divergent.
**Shape**: confirmed. This is an environment skew between substrate (homebrew Catch2)
and remote CI (vendored Catch2). Failure mode: build fails on main *and* every
branch on this host.
**Provenance**:
- Origin commit of GoldenTest.h: predates main HEAD (cc6c293 → still present unchanged).
- This is project test infrastructure, not our code. Adding the missing include is a
  maintainer-side cleanup, not a fix-PR concern.

## Diagnosis

The attest verdict `test_fails_on_fix` is a **false attestation**. The fix is not
broken; the substrate's local test environment cannot build *any* branch of
slang-server because the host's homebrew Catch2 conflicts with `GoldenTest.h`'s
include layout. Remote CI is green. The PR itself is sound.

**Reasoning modes**:
- H₀, H₁, H₂, H₃: induction (ran the build, observed the error).
- "False attestation" claim: deduction from observed identity on main.

## Recommendation (no PR change)

This is a substrate/env mismatch, not a fix defect. Three operator-side options:

1. **Patch local include** (one-line) — add `#include <catch2/interfaces/catch_interfaces_capture.hpp>` to `tests/cpp/utils/GoldenTest.h`. This restores the build locally but is unsolicited cleanup on maintainer test infra. Following "go with the flow / imitate, do not reform": not our call to ship.
2. **Pin Catch2 in the worktree's submodules** so local build uses the project's intended version, not homebrew. The project's `test_setup_cmd` runs `git submodule update --init --recursive --depth 1`. Verify whether Catch2 is meant to be vendored vs system-supplied.
3. **Evict this repo from attest** (`retro_param test_env=evict` or similar) — accept that this repo's local build is incompatible with current substrate host until Catch2 alignment is fixed. PR can proceed without behavioral attestation, relying on remote CI as the gate.

Frontier edge (not pursued, requires gh): does the project's CMakeLists.txt fetch a
pinned Catch2 in the bundled-deps path, or `find_package(Catch2)` against system? That
determines whether option (2) is even feasible.

## Halt

PR #342 stands as-is. No new commit produced. The attest false-positive is a substrate-
side concern; routing back as a `human-gated` signal for the operator to choose between
options 1–3.
