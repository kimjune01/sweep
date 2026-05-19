# cachix/devenv#2828 — `devenv build` JSON is flat instead of nested

## H₀ — flat output is the build pipeline's intentional shape

**Observation.** `devenv build` returns a JSON object whose keys are dot-separated attribute paths (`"outputs.foo.bar": "/nix/store/..."`) instead of a nested object mirroring the `outputs` tree.

**Perturbation.** Trace the serialization path from the `Commands::Build` dispatch.

**Evidence (deduction, 99%).**

- `devenv/src/main.rs:815-825` — dispatcher does:
  ```rust
  let results = devenv.build(&attributes).await?;  // Vec<(String, PathBuf)>
  let json_map: serde_json::Map<String, serde_json::Value> = results
      .into_iter()
      .map(|(attr, path)| (attr, serde_json::Value::String(path.display().to_string())))
      .collect();
  ```
  Each `(attr, path)` becomes one top-level key — by construction the result cannot nest.
- `devenv/src/devenv/mod.rs:1391-1469` — `Devenv::build()` runs `flatten_object()` over the evaluator's nested `outputs` tree (`prefix.k.k2.k3`), then passes the dot-joined strings to the backend's `build_devenv` and zips them back with paths. So the flat shape is *manufactured* on the way in, then serialized verbatim on the way out.

**Trajectory.** Divergent — the flat shape is what the code produces, no other code path emits the build result.

**Kill condition / edge.** None to follow — the cause is found. Move to provenance.

## Phase 2.5 — Provenance

- **git blame.** `devenv/src/main.rs` Build arm was introduced by `9486594 hook: fix "infinite loop detected" ...` (rebuild of main.rs). It has been touched only for unrelated lints (`ec73bd5 devenv: lint tracing setup and various bits`) — the flat-map shape has never been reconsidered. It is an *inherited default*, not a deliberate design statement, but also not a bug that snuck in.
- **Issue tracker.** No other open issues mention nested-vs-flat build output. No related PRs in the pre-fetched search (`#2806/#2809/#2813/#2838` are unrelated). No maintainer comment on #2828.
- **Reporter signal.** The reporter writes "I guess this is a breaking change, maybe for v3 :)" — they explicitly do not request an immediate fix and acknowledge the JSON contract.

## H₁ — A nested-by-default fix is shippable now

**Null.** The maintainer treats this as a v3 / breaking-change item and rejects a "fix-by-changing-output-shape" PR opened against current main.

**Perturbation.** Mental walkthrough of the change cost and risk:

- Implementation is trivial: re-nest the dot-separated keys into a `serde_json::Value` tree in `Commands::Build` (5-10 lines), or push nesting back into `Devenv::build` so the flatten/zip round-trip is removed.
- But `devenv build` is a public JSON-emitting CLI. Any consumer parsing `"outputs.foo.bar"` keys today breaks. The reporter themselves frames this as v3 material.
- No maintainer ack, no `good-first-issue` / `accepting-PRs` label (only `bug`), and no prior kimjune01 PRs on this repo to establish trust.

**Trajectory.** Divergent against shipping. The change is structurally easy but socially premature.

**Status.** Killed by provenance + reporter's own deferral. Edge: write up the diagnosis, stop before the side-effect (PR).

## Phase 4.5 — Reframe

The investigation's output is not a fix — it is the confirmation that the reporter's "maybe for v3" framing is correct:

- The flat shape is generated upstream (`flatten_object`) and serialized verbatim downstream. A nested fix is small but breaks a public contract.
- No maintainer signal exists to authorize the break.
- Per the repo conventions rule ("imitate, do not reform"): we don't get to declare the JSON contract change on the maintainer's behalf.

**Decision.** Halt at diagnosis. Do not ship. If a maintainer later confirms intent (label change, comment, or a v3 milestone opens), re-enter at Phase 5 with a minimal patch:
- Move `flatten_object` out of `Devenv::build`; have it return `Vec<(Vec<String>, PathBuf)>` (path components, not dot-joined).
- In `Commands::Build` build a `serde_json::Value` tree by walking the components.
- Add a CHANGELOG entry under breaking changes.

## Graph state

| Node | Status | Shape |
|------|--------|-------|
| H₀: flat-by-construction in `Commands::Build` + `flatten_object` | confirmed | divergent |
| H₁: nested-by-default shippable now | killed (provenance + reporter deferral) | divergent against |

## Frontier edges

None open. Awaiting external signal (maintainer comment or v3 milestone) before re-entering.

## Reasoning mode

- H₀ confirmation: deduction (read the code path), 99%.
- H₁ kill: abduction over social signal (reporter wording, no maintainer ack, no labels), 80%.
