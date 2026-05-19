# cachix/devenv#2840 — garage configureScript not executed with process-compose

## Issue summary

`services.garage.configureScript` is wired as `tasks."devenv:garage:configure"`, with the garage process declaring `before = [ "devenv:garage:configure" ]`. Reporter @gabyx observed that the configure script never runs under the `process-compose` manager, so buckets declared in `services.garage.buckets` are never created and S3 traffic is rejected (Garage refuses requests until cluster layout is applied).

## H₀ — task is dropped by process-compose dep translation

**Hypothesis:** the process-compose integration only translates `before` entries that name OTHER processes; entries naming oneshot tasks are silently dropped.

**Perturbation:** read `src/modules/process-managers/process-compose.nix` and `src/modules/lib/parse-process-dep.nix`.

**Evidence:**
- `parseProcessDep` (parse-process-dep.nix:23) returns `null` unless the name has the `devenv:processes:` prefix.
- `beforeDepsMap` filters those nulls out (process-compose.nix:16: `lib.filter (x: x != null) (map parseProcessDep process.before)`).
- The garage `before = [ "devenv:garage:configure" ]` is therefore never emitted as a process-compose `depends_on`.

**Trajectory: divergent — confirmed.** The task is not visible to process-compose's dependency graph at all.

## H₁ — per-process devenv-tasks invocation should still pick configure up

**Hypothesis:** even though process-compose drops the dep, each process is launched via `exec devenv-tasks run --mode all --ignore-process-deps devenv:processes:garage` (processes.nix:505), and `--mode all` traverses outgoing edges, so `devenv:garage:configure` is in the per-process subgraph.

**Evidence:**
- `RunMode::All` in `devenv-tasks/src/tasks.rs:468` traverses both incoming (predecessors) and outgoing (dependents) from each root. configure (outgoing from `devenv:processes:garage`) is added.
- `ignore_process_deps` (tasks.rs:512) only prunes non-root *process-type* tasks. configure is oneshot → survives.
- configure's incoming dep on `devenv:processes:garage` resolves with `DependencyKind::Ready` by default (tasks.rs:361), so configure should wait for the ready probe.

**Trajectory: oscillatory.** Static analysis says configure *should* run, but the reporter's empirical evidence says it doesn't. Two possibilities:
- (a) There's a subtle bug in the per-process invocation under process-compose (e.g. the devenv-tasks subprocess exits or doesn't actually schedule configure when launched inside process-compose's process slot).
- (b) The pattern works in `native` mode (where the orchestrator owns everything) but breaks in `process-compose` mode for an interaction we haven't traced.

Either way, the *fix* doesn't depend on settling this — there's a proven-working alternative in the same repo.

## H₂ — minio.nix's inline pattern is the established workaround

**Hypothesis:** the inline `start → background → poll → afterStart → wait` pattern in `minio.nix` is the proven pattern for post-start configuration in this codebase. It doesn't depend on the task graph at all; it lives entirely inside the process's exec script.

**Evidence:** `src/modules/services/minio.nix:33-50` — when `afterStart != ""`, minio:
1. backgrounds the server (`${serverCommand} &`),
2. polls readiness in a loop (`while ! mc admin info local; do sleep 1; done`),
3. runs `${cfg.afterStart}`,
4. `wait`s on the backgrounded server (so the process slot stays alive).

This works under any process manager because it's just a shell script.

**Trajectory: divergent — confirmed working pattern.**

## H₃ — mysql.nix uses the same broken task pattern as garage

**Evidence:** mysql.nix:345 — `processes.mysql.before = [ "devenv:mysql:configure" ]`. The tests/mysql/.test.sh queries the configured user, but with a `sleep 5` hack — suggesting flakiness even when it does work. Mysql tests probably pass under `native` (default for devenv 2.0+).

**Frontier edge (out of scope for this PR):** mysql may have the same latent bug under process-compose. Don't fix mysql in this PR; the maintainer asked about garage. Mention it in the PR description as related risk.

## Diagnosis

The `processes.X.before = [<task>]` pattern is not honored by the process-compose integration. The garage module should follow the minio pattern: inline the configure logic into the process exec, polling for readiness before running cluster setup and bucket creation.

A secondary issue: `tests/garage/.test.sh` only checks the admin health endpoint, which would succeed even if configure never runs. The test should verify bucket creation — exactly what the issue reporter pointed out.

## Provenance

- garage.nix introduced in PR #2781 (May 2026, @ap-1). PR description says it "mirrors the mysql / rustfs pattern of using a separate task gated by `processes.X.before`". rustfs.nix actually uses a *pre-start* setup task (different direction); only mysql uses the post-start pattern.
- No prior issues found for garage configure not running. Reporter @gabyx filed #2840 today.

## Proposed fix

Rewrite `src/modules/services/garage.nix` to:
1. Drop `tasks."devenv:garage:configure"` and the `processes.garage.before = [ ... ]`.
2. Inline the configure script into a `startScript` wrapping `garage server`, mirroring minio.nix:33-50.
3. When `cfg.buckets == []` AND `cfg.afterStart == ""`, exec garage directly (no wrapping overhead).
4. Update `tests/garage/.test.sh` to verify the bucket exists via the S3 API.

## Reasoning mode table

| Hypothesis | Mode | Confidence |
|-----------|------|-----------|
| H₀ task dropped | Deduction (code trace) | 99% |
| H₁ per-process subgraph | Deduction + abduction | 70% (says works, reporter says doesn't) |
| H₂ inline pattern works | Induction (minio precedent) | 95% |
| H₃ mysql also affected | Abduction | 60% — not investigated, flagged as frontier |
