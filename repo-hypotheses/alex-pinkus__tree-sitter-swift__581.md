# Hypothesis Graph: alex-pinkus/tree-sitter-swift#581

PR: https://github.com/alex-pinkus/tree-sitter-swift/pull/581 (OPEN, mergeable, no review)
Branch: `fix-550-nonisolated-unsafe` @ 376f4622
Re-investigation trigger: attest gate failed — CI red on `Check compilation/bindings/style`

## Phase 1: Observation (H₀)

PR CI status:
- `Check compilation on tree-sitter 0.19` — SUCCESS (2026-05-12, at PR open)
- `Parse top repositories` — SUCCESS (2026-05-12, at PR open)
- `Check compilation/bindings/style` — **FAILURE** (2026-05-16, re-run / newer commit)

Failure log tail (run 25707802122):
```
> tree-sitter-swift@0.7.2 ci
npm error Missing script: "ci"
##[error]Process completed with exit code 1.
```

**H₀ classification: divergent.** CI failure is reproducible and localized to a single missing npm script. Not a grammar bug; an infrastructure regression introduced by the PR.

## Phase 2: Fan-out

### H₁: Grammar fix itself broke CI
**Perturbation**: read grammar.js diff.
**Result**: grammar.js change is one line, surgical, adds `"nonisolated(unsafe)"` to `member_modifier` choice. Other CI jobs that exercise the grammar (tree-sitter 0.19, Parse top repositories) PASSED.
**Trajectory: divergent against.** Grammar fix is fine. KILLED.

### H₂: PR overwrote modernized `package.json` with stale version
**Perturbation**: `git diff origin/main..HEAD -- package.json`.
**Result**: PR removes 6 scripts from main's package.json:
- `postinstall`, `build`, `build-wasm`, `ci`, `test-ci`, `prebuildify`
And replaces `test` with an older form. CI workflow `check.yml` invokes `npm run ci` (prettier check) and `npm run test-ci` (memcheck) — both now missing.
**Trajectory: divergent confirming.** CONFIRMED root cause for CI failure.

### H₃: Stale-CLI regeneration also damaged `src/grammar.json` and `src/node-types.json`
**Perturbation**: diff src/* against main.
**Result**:
- `src/grammar.json` lost `$schema` field and `reserved: {}` field; trailing newline changed
- `src/node-types.json` lost `root: true` on `source_file`, lost `extra: true` on `comment`/`multiline_comment`, gained spurious node types `delegate`, `param`, `property`
These changes look like output from an OLDER tree-sitter CLI version regenerating against a newer grammar.js. The maintainer's `./scripts/check-dirty.sh` step in CI would also fail because regeneration on the runner (with current CLI) would produce a different diff than what's committed.
**Trajectory: divergent confirming.** CONFIRMED secondary damage.

### Provenance check
- The two PR commits are: `2ad1980 fix: support nonisolated(unsafe) modifier (#550)` and `376f462 Add comprehensive corpus test for nonisolated variants`.
- The damaging commit is `2ad1980`: it touched `package.json`, `src/grammar.json`, `src/node-types.json` in the same commit as the grammar.js fix, almost certainly from a `tree-sitter generate` invocation run against a worktree that was either branched from older main OR using a locally-installed tree-sitter CLI older than what main expects.
- Main HEAD: `3d38a39`. Merge base of our branch with origin/main: `3d38a39` (we're up to date with main locally — the staleness was in the regeneration tooling, not the branch base).

## Causal chain

`tree-sitter generate` invoked with stale CLI → regenerated `src/grammar.json` & `src/node-types.json` with old-format output → simultaneously, `package.json` was accidentally reverted (likely from same regen step or local IDE state) → committed alongside legitimate grammar.js fix → CI's `npm run ci` step now fails because the `ci` script no longer exists.

## Fix shape

Surgical revert of three files, keep grammar.js and test/corpus/classes.txt:

1. **`package.json`** — checkout origin/main version verbatim.
2. **`src/grammar.json`** — checkout origin/main, then add one entry to `member_modifier.members` for `"nonisolated(unsafe)"` (a STRING node).
3. **`src/node-types.json`** — checkout origin/main, then add one entry `{"type": "nonisolated(unsafe)", "named": false}` in sorted position.
4. **`grammar.js`** — keep as is.
5. **`test/corpus/classes.txt`** — keep as is.

This produces a minimal, clean diff: one-line grammar.js change + corpus tests + two surgical generated-file additions, matching what `tree-sitter generate` (current CLI) would produce on top of clean main.

## Frontier edges

- E1: After surgical fix, push and watch the `Check compilation/bindings/style` workflow re-run. If `check-dirty.sh` still fails, it means current tree-sitter CLI produces a *different* diff than our hand-edit; resolve by running `tree-sitter generate` in the runner's environment OR by matching the CLI version locally.
- E2: `npm run test-ci` invokes `./scripts/test-with-memcheck.sh --install-valgrind`. Even after fixing `ci`, this step might fail if our corpus test names collide with existing patterns. (Low risk; corpus tests added under fresh names.)

## Reasoning mode table

| Claim | Mode | Confidence |
|-------|------|-----------|
| `npm run ci` fails because script absent | Induction (CI log) | 99% |
| package.json regression is the cause | Deduction (read diff) | 99% |
| Stale CLI regenerated src/* | Abduction (shape of diff matches old format) | 80% |
| Surgical revert will fix CI | Deduction + induction-pending | 90% |

## Pruning log

- H₁ (grammar fix is buggy): killed by other CI jobs passing on identical grammar.js change.
