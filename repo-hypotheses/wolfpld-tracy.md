# Triage Graph: wolfpld/tracy

**Repo**: wolfpld/tracy
**Stars**: ~15942
**Language**: C++
**Description**: Real time, nanosecond resolution, remote telemetry frame profiler for games and other applications
**Date**: 2026-05-13

## Repo Profile

Tracy ships two artifacts under one repo:
- **Client** (`public/client/`, `public/tracy/`) — pure C++ instrumentation library, header-only-ish, no UI.
- **Server / profiler GUI** (`server/`, `profiler/`) — Dear ImGui-based desktop UI.

Per `feedback_no_gui_tui` the GUI server is out of scope. Per the task carve-out, the **client library, protocol/serialization layer, and CLI tools** (`csvexport`, `capture`) are eligible if a fix is mechanically verifiable without a real profiling workload.

**AI policy**: `~/.sweep/bin/ai-policy wolfpld/tracy` returned `detected: false`. No CONTRIBUTING.md, no AGENTS.md. README links to a PDF for build/usage; no contribution policy text. No CLA. Solo-maintainer style (wolfpld is the dominant author, with regular external PRs merged — see #1330 merged 2026-04-06).

**Branch policy**: standard PRs to `master`. No squash/commit-limit constraints visible. No AI disclosure requirement (none documented anywhere accessible).

**Standing**: zero merged PRs from kimjune01. Cold start. First PR must be the smallest, most boring, maintainer-acknowledged bug.

## Hypothesis

**H0**: A small, maintainer-acknowledged client-library bugfix with a clear surface (no UI, no profiling-runtime verification needed) merges. Architectural changes and unacknowledged "I think this is wrong" reports do not.

## Issues Investigated

### #1264: UB in TracyCUDA.cpp attempting to read string_view end()
**Status**: PICKED
**Created**: 2025-09-xx
**Comments**: 3
**File**: `public/tracy/TracyCUDA.hpp` lines 431–432
**Body-count**: clear (0 closed-unmerged authors)
**Competing PRs**: none (`gh pr list --search "TracyCUDA UB string_view"` empty; no open CUDA PRs touch this code path)

**The bug**:
```cpp
tracy::SourceLocationData* add(std::string_view function, std::string_view file, int line, uint32_t color=0) {
    ZoneNamed(emplace, instrument);
    assert(*function.end() == '\0');   // UB: dereferences end()
    assert(*file.end() == '\0');       // UB: dereferences end()
```
`std::string_view::end()` returns a past-the-end iterator; dereferencing it is UB and is observed as a runtime trap on Windows (reporter btipling).

**Maintainer engagement**: wolfpld responded directly: confirmed the bug AND rejected the obvious workaround (`function.data()[function.size()] == '\0'`) as still UB because the underlying buffer can end on a page boundary. So this is acknowledged + the trivial fix is pre-rejected. The space of acceptable fixes is narrow — that narrowness is what makes it a good first PR (low scope-creep risk).

**Acceptance shape** (to be refined by /investigate): the asserts are checking an unverifiable precondition (NUL-terminated storage backing a `string_view`). Two viable fixes:
1. **Drop the asserts.** They cannot be safely expressed against `string_view`. Document the precondition in a comment instead. Callers (lines 397–400, 983) already pass NUL-terminated storage by construction.
2. **Change the API** to take `const char*` instead of `string_view`, removing the ambiguity at the type level. Larger surface, more invasive.

(1) is the smaller fix; /investigate decides.

**Verifiability without profiling workload**: yes — the asserts fire on every `add()` call in debug builds. A one-line C++ test that builds against TracyCUDA.hpp and exercises the path will trap on master and pass after the fix. Static analyzers (clang `-fsanitize=undefined`) flag the original code.

**Why this and not others**:
- #1192 (TracyVector destructors): architectural; touches 25+ call sites; likely not bounded.
- #1232 (TracyPlotConfig color byte order): no maintainer engagement; references closed PR #514; risk of "working as intended."
- #1184 (Misleading error message): server-side worker code; UI-adjacent; no maintainer response.
- #1195 (Android getlogin overflow): already fixed in commit 89f68bab.
- #1019, #1294, #1297, #1306, #1303 (crashes / runtime issues): require live profiling sessions to reproduce.
- #1049, #1165 (csvexport CSV/sep): CLI tool, eligible, but #1165 is "RTFM use `--sep=;`" not a bug; #1049 is a design call (CSV quoting vs. delimiter choice) without maintainer endorsement.
- #1264 is the only issue that is (a) maintainer-confirmed, (b) in client/non-UI code, (c) verifiable without a real GPU workload, and (d) bounded in scope.

## Picked

**#1264** — UB in `TracyCUDA.hpp` `add()` asserts. Drop or replace the UB asserts after /investigate produces the hypothesis graph and confirms the maintainer's position via the comment thread.

## Hypothesis Graph (post-investigate, 2026-05-13)

| H | Description | Cost | Risk | Decision |
|---|---|---|---|---|
| H0 | Drop the asserts entirely; document precondition in comment | 4 lines, no API change | Loses runtime check (already untrustworthy — only fired in debug, only on the one path that already passes NUL-terminated storage by construction) | **PICKED** |
| H1 | Change API: `std::string_view` → `const char*` | 6+ call sites in this header (`add`, `retrieve`, `StringTable::operator[]`, `SourceLocationMap` map key type), changes hash-map key type from sv to const char* (lifetime/equality semantics shift) | High blast radius for a "paranoid assert" fix; API change for a solo maintainer's first PR is over-scope; maintainer's collaborator (slomp) explicitly framed asserts as "paranoid" — not load-bearing | rejected as scope creep |
| H2 | Keep `string_view` but verify NUL-termination via a different mechanism (e.g., compile-time-pinned source-location table) | Requires reworking how kernel names flow through `StringTable` and `SourceLocationMap` | Architecturally large; orthogonal to the bug | rejected |

**Picked**: H0. Rationale chain:
1. Maintainer @wolfpld confirmed bug; pre-rejected `data()[size()]` workaround as still UB (page-boundary).
2. Collaborator @slomp described the asserts as "paranoid" and committed to patching → signals that dropping them is the maintainer's preferred direction.
3. Both call paths (`SourceLocationMap::add` is called once at line 1088) already pass NUL-terminated storage by construction:
   - `demangledName` is memoized via `StringTable::operator[]` which explicitly NUL-terminates its copy (line 405: `copy[str.size()] = '\0';`).
   - `TracyFile` is `__FILE__`, a string literal.
4. There is **no portable, runtime-safe way** to verify NUL-termination of `string_view` storage. Any "smart" check is itself UB or fragile. The honest fix is to drop the false-confidence runtime check and document the contract.
5. Two commits: (a) fix the UB + function-level precondition comment, (b) hoist the precondition to the struct-level doc so callers don't have to read `add()`'s body.

## Outcome

- Branch: `fix-tracycuda-stringview-end-ub` on `kimjune01/tracy`
- Commits: `43406636` (fix) → `c8ee61a1` (struct doc)
- Attestation: `~/.sweep/repos/wolfpld-tracy/attestations/issue-1264-20260513T233116Z.txt`
- UBSan/ASan: master pattern aborts (exit 134); fix is clean (exit 0).
