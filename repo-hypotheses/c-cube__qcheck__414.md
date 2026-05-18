# c-cube/qcheck#414 Hypothesis Graph

Investigation timestamp: 2026-05-18T15:51:03Z

Target: PR `c-cube/qcheck#414`, branch `add-dep-pair-generator`
Local perturbation surface: `/Users/junekim/.sweep/worktrees/c-cube__qcheck`

## Graph State

| Node | Status | Trajectory | Summary |
|---|---|---|---|
| H0 | refined | divergent | Prior attestation classified the PR as broken, but the only failure evidence is `dune: command not found`; this is an environment/tooling failure, not a code failure. |
| H1 | partial | convergent | The branch implements the requested `QCheck2.Gen.dep_pair` shape using existing `bind` and `pair` primitives, and the code is structurally consistent with `Gen` conventions. |
| H2 | confirmed | divergent | The public API addition is missing low-risk release/documentation polish: a `CHANGELOG.md` entry and an `@since` tag in `QCheck2.mli`. |
| H3 | open | chaotic | Executable verification is unavailable locally because `opam`, `ocamlc`, and `dune` are absent, and Docker daemon access is blocked by sandbox permissions. |

## H0: Attestation Failure Means Fix Is Broken

Hypothesis: The current PR branch is broken.

Null: The attestation failure is an artifact of the local test environment.

Perturbation:
- Read `/Users/junekim/.sweep/inbox/reinvestigate.jsonl`.
- Read `/Users/junekim/.sweep/attestations/qa-20260518T044453-c-cube-qcheck-414/{codex.txt,gemini_r1.txt}`.
- Check local tool availability with `opam --version`, `ocamlc -version`, and `dune --version`.

Trajectory:
- Reinvestigate payload says: `test_fails_on_fix — fix is broken: bash: line 1: dune: command not found`.
- Codex and Gemini attestation files are stubs: wrappers not implemented.
- Local shell also lacks `opam`, `ocamlc`, and `dune`.

Shape: divergent against the original "fix is broken" classification.

Kill condition: A code-breaking failure would include compiler/test output from the PR branch; the observed failure is missing test tooling.

Edge: Reclassify as environment-blocked verification; continue with structural review.

Reasoning mode: induction from local command output, 90% confidence.

Provenance:
- Source of failure: attestation card `reinvestigate-from-attest-20260518T052736-c-cube-qcheck-414`.
- Risk assessment: not evidence against the PR implementation.

## H1: `dep_pair` Implementation Satisfies the API Shape

Hypothesis: `QCheck2.Gen.dep_pair` can be implemented as `g >>= fun x -> pair (pure x) (f x)`.

Null: The implementation violates generator/shrinker semantics or uses unavailable symbols.

Perturbation:
- Inspect `src/core/QCheck2.ml` around `Gen.bind`, `Gen.pair`, and the new `Gen.dep_pair`.
- Inspect `src/core/QCheck2.mli` docs for `bind`, `pair`, and the new API.
- Inspect added unit test in `test/core/QCheck2_unit_tests.ml`.

Trajectory:
- `Gen.bind` is defined before `dep_pair`.
- `Gen.pair` is defined immediately before `dep_pair`.
- The second commit fixed an earlier unbound `tup2` reference by using `pair`.
- The unit test generates arrays of length `1..100` and indexes bounded by `Array.length arr - 1`, checking all generated samples are valid.

Shape: convergent.

Kill condition: This node remains partial because compile/runtime tests could not run in this sandbox.

Edge: Keep implementation shape; seek executable verification in an OCaml-capable environment or CI.

Reasoning mode: deduction from code trace, 95% confidence for symbol ordering; induction blocked for runtime semantics.

Provenance:
- Origin commits: `c0bf555` added `dep_pair`; `5e8914a` fixed `tup2` to `pair`.
- Adjacent mechanism: `bind` already supports dependent generators; `dep_pair` is a convenience wrapper preserving the first generated value.
- Risk assessment: low functional risk; main remaining risk is unrun compile/test validation.

## H2: API Documentation/Release Polish Is Missing

Hypothesis: The PR should include the same release-note/doc metadata expected for nearby public `QCheck2.Gen` additions.

Null: The project does not require changelog or `@since` entries for new generator APIs.

Perturbation:
- Search `CHANGELOG.md` for recent `QCheck2.Gen` additions.
- Search `src/core/QCheck2.mli` for neighboring `@since` annotations.

Trajectory:
- `CHANGELOG.md` has a `NEXT RELEASE` section and many entries for added/renamed `QCheck2.Gen` APIs.
- Neighboring recent public APIs such as `array_small`, `flatten_list`, and `map_keep_input` include `@since` tags.
- The new `dep_pair` API has neither a changelog line nor an `@since` tag.

Shape: divergent for missing metadata.

Kill condition: If maintainers explicitly omit `@since NEXT_RELEASE` for unreleased APIs, revise to the concrete next version or drop the tag.

Edge: Apply a minimal polish patch.

Reasoning mode: deduction from repository convention, 95% confidence.

Provenance:
- Existing convention: `CHANGELOG.md` `NEXT RELEASE`; `src/core/QCheck2.mli` public API docs.
- Risk assessment: very low; no behavior change.

Proposed patch:

```diff
diff --git a/CHANGELOG.md b/CHANGELOG.md
@@
 ## NEXT RELEASE (202?-??-??)
 
+- Add `QCheck2.Gen.dep_pair` for dependent pair generation.
 - Remove optional `gen` parameter from (API breaking):
diff --git a/src/core/QCheck2.mli b/src/core/QCheck2.mli
@@
       Shrinks on the first element and then on the second element (given
       the shrunk first element).
+
+      @since NEXT_RELEASE
   *)
```

## H3: Local Verification Surface Is Blocked

Hypothesis: The PR can be verified locally with targeted `dune` tests.

Null: The local environment cannot execute OCaml tests.

Perturbation:
- `opam --version`
- `ocamlc -version`
- `dune --version`
- `docker image ls sweep-tester:latest`

Trajectory:
- `opam`, `ocamlc`, and `dune` are not found.
- Docker CLI exists, but connecting to the Orbstack Docker socket is denied by sandbox permissions.

Shape: chaotic for local runtime verification; the perturbation surface is incomplete.

Kill condition: Install/use an OCaml-capable environment or run CI.

Edge: Do not classify code as broken from this environment; queue CI or external attest.

Reasoning mode: induction from local command output, 90% confidence.

## Frontier Edges

| Edge | Perturbation | Predicted classification | Confidence |
|---|---|---|---|
| E1 | Apply the changelog/`@since` patch to PR branch. | convergent | 90% |
| E2 | Run `dune runtest test/core` or the project’s targeted core tests in an OCaml environment. | divergent pass or real compile error | 70% |
| E3 | Check PR CI status through GitHub once network/API access is available. | convergent if green; divergent if real CI failure | 75% |

## Reasoning Mode Table

| Claim | Mode | Confidence |
|---|---|---|
| Prior failure is environment/tooling, not code. | induction | 90% |
| `dep_pair` uses already-defined `bind`, `pair`, and `pure`. | deduction | 95% |
| Missing changelog/`@since` is a repo-convention gap. | deduction | 95% |
| Runtime behavior is correct. | abduction pending induction | 65% |

## Pruning Log

| Node | Pruned? | Why |
|---|---|---|
| H0 original | yes | Killed by the failure message itself: `dune` missing is not a fix regression. |
| "Codex/Gemini found issues" | yes | Attestation files contain only wrapper stubs, no findings. |

## Environment Notes

- Shell GitHub API access failed: `error connecting to api.github.com`.
- Web access to the issue/PR page was not available enough to recover PR body/comments.
- `codex exec` is installed but cannot initialize its app-server client in this sandbox: `Operation not permitted`.
- Direct edits to `/Users/junekim/.sweep/worktrees/c-cube__qcheck` are blocked by writable-root restrictions; the patch above must be applied from an environment allowed to write that worktree.
