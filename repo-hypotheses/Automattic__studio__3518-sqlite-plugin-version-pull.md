# Automattic/studio#3518 - SQLite plugin version on database pull

Issue: https://github.com/Automattic/studio/issues/3518

Opened: 2026-05-16 (observed from GitHub issue list)

Title: `"Could not determine the version of the SQLite integration plugin" on pull of database from WordPress.com site`

Environment routing:

- `sweep project-info Automattic/studio` returned `worktree=/Users/junekim/.sweep/worktrees/Automattic__studio`, `worktree_exists=false`, `test_env=docker:sweep-tester:latest`, no canonical test command.
- Sandbox cannot create the canonical worktree path (`Operation not permitted`).
- Shell DNS cannot resolve GitHub for `git clone` or `gh issue view`; executable perturbation access is currently unavailable.
- Public web access can read GitHub repository/issue-list pages and WordPress Studio changelog pages.
- `codex` CLI exists (`codex-cli 0.130.0`) but `codex exec` cannot initialize in this sandbox (`Operation not permitted`), so structural filtering is unavailable.
- Git has a global rewrite from `https://github.com/` to `ssh://git@github.com/`; bypassing it with `https://github.com:443/...` still fails because shell DNS cannot resolve `github.com`.

## H0 Observation

| Field | Value |
|---|---|
| Hypothesis | Pulling a WordPress.com database into Studio can fail before or during SQLite integration compatibility handling because Studio cannot determine the local SQLite Database Integration plugin version. |
| Null | The issue is user/environment-specific and the app has enough local metadata to determine the SQLite plugin version during database pull. |
| Perturbation | Baseline attempted: fetch target worktree and issue body, then run the most direct local reproduction. |
| Result | Worktree fetch failed in shell due DNS; canonical worktree is outside writable sandbox. GitHub issue list confirms the issue exists and is open, with the exact title. No executable reproduction was possible. |
| Trajectory shape | Chaotic/access-limited. The perturbation did not isolate application behavior; it isolated an environment access failure. |
| Kill condition | If repo checkout and issue reproduction become available, H0 must be retested with a real database-pull scenario. |
| Edge | Fan out hypotheses from the issue title and public release/changelog evidence, but keep confidence capped at abduction level until code is measurable. |
| Reasoning mode | Induction for access failure; abduction for product failure shape. |
| Confidence | 90% that local perturbation access is blocked in this session; 65% that the title points at SQLite plugin metadata handling. |

## Blind-Blind Pushout

Independent hypothesis passes:

- A: explorer `019e3bf8-4140-7ba2-beee-d1b76fa6d0a9`
  - Root cause: brittle SQLite Database Integration plugin version detection during database pull, likely caused by newer plugin packaging/runtime layout, missing transient plugin files, directory/name drift, or changed metadata format.
  - Fix shape: centralize version detection, try multiple sources, distinguish missing/unparseable/unavailable states, and avoid hard-failing when the bundled plugin can be safely installed or upgraded.
  - Confidence: 35%.
- B: explorer `019e3bf8-537a-7b41-88f0-0d474087ba6e`
  - Root cause: Studio cannot map the remote WordPress.com/Playground/SQLite plugin representation to a known supported version; unknown version is treated as fatal.
  - Fix shape: tolerant and observable detection with explicit result types: detected, unknown, not-installed, incompatible. Prefer capability detection when exact version is not required.
  - Confidence: 55%.

### Where A and B Diverge

| Axis | A | B | Investigative edge |
|---|---|---|---|
| Primary failure surface | Local/transient pulled filesystem, plugin layout, or parser brittleness. | Remote WordPress.com/Playground representation and version-to-capability mapping. | Test whether error occurs before local plugin files exist, while reading remote metadata, or after command-file generation. |
| Fallback policy | Install/upgrade bundled plugin if exact version is unavailable and safe. | Prefer capability detection over exact version if pull mechanism is available. | Determine whether current pull behavior actually needs a semantic version or only needs a feature/capability. |
| Confidence | 35% | 55% | Keep merged confidence at 50% until code and reproduction exist. |

Agreement: the next useful node is not "change SQLite support" broadly; it is to locate the exact version detector and classify whether the missing evidence is local files, remote metadata, parser drift, or command-file timing.

## H1 Merged Hypothesis

| Field | Value |
|---|---|
| Hypothesis | Studio's database pull flow hard-fails when SQLite plugin version detection returns unknown, and the detector is brittle across current plugin packaging, remote metadata, or transient setup states. |
| Null | The detector is correct; the source site or pull API lacks required information, and the right fix is only better diagnostics or unsupported-state handling. |
| Perturbation | Pending executable code access: search for exact error, trace call site, create fixtures for missing version, current `2.2.17`, unexpected plugin path, missing filesystem, and delayed/corrupt `sqlite-command` output. |
| Trajectory shape | Pending. Predicted divergent if one detector call site produces the user-facing error from an unknown/missing version state. |
| Kill condition | If exact error is thrown by a generic database-pull catch block unrelated to version detection, H1 dies and the edge becomes generic error wrapping or API payload failure. |
| Edge | H2: classify source of unknown version: local filesystem, remote metadata, parser drift, command-file timing, or generic catch-all. |
| Reasoning mode | Abduction, generated by blind pushout A+B. |
| Confidence | 50%. |

## Graph State

| Node | Status | Shape | Confidence | Notes |
|---|---|---|---:|---|
| H0 | partial | chaotic/access-limited | 65% | Issue title observed; code reproduction blocked. |
| H1 | open | pending | 50% | Blind pushout converged on brittle/over-fatal SQLite plugin version detection. |
| H2 | human-gated/access-blocked | chaotic/access-limited | 95% | Perturbation access to repo/code is unavailable in this session. |

## Frontier Edges

| Edge | Next perturbation | Predicted classification | Confidence |
|---|---|---|---:|
| E0a: missing plugin files | With code available, inspect database pull path for assumptions that `wp-content/plugins/sqlite-database-integration` exists after pulling only database. Reproduce with database-only pull where active plugins option includes SQLite plugin but plugin files are absent. | Divergent if version read throws before ensuring plugin files. | 60% |
| E0b: plugin slug/path mismatch | Inspect version detection for hard-coded plugin slug/path versus actual installed plugin directory/file names across bundled, pulled, and upgraded sites. | Divergent if version metadata lookup uses stale slug. | 45% |
| E0c: version parser brittle | Inspect parser for `readme.txt`, plugin header, `version.php`, or package metadata. Test with SQLite plugin 2.2.x layouts. | Convergent if parser handles old layout but not current layout. | 50% |
| E0d: concurrent setup race | Inspect site setup/pull sequence for sqlite-command or plugin-copy ordering; test concurrent pull/setup where version detection races file copy. | Oscillatory if only concurrent or cold-start paths fail. | 40% |
| E1a: exact error call site | `rg "Could not determine the version of the SQLite integration plugin"` in the worktree; trace throw/catch path. | Divergent if the message has a unique call site. | 80% once code exists |
| E1b: remote-vs-local source | Instrument or unit-test detector input source: remote metadata/API, local filesystem, plugin header, or command file. | Divergent if one source is exclusively used. | 65% once code exists |
| E1c: capability-vs-version | Inspect downstream uses of detected version. If only gating a feature, replace exact-version requirement with capability detection or safe fallback. | Convergent if version is proxy for capability. | 50% once code exists |
| E2a: restore perturbation access | Provide or create a local checkout under a writable path, or run in an environment where shell DNS/GitHub access works. Then resume from E1a. | Divergent if exact call site is found. | 95% |

## Reasoning Modes

| Claim | Mode | Ceiling | Current confidence |
|---|---|---:|---:|
| The shell cannot fetch GitHub or use `gh` in this session. | Induction | 95% | 90% |
| The canonical worktree path is blocked by sandbox permissions. | Induction | 95% | 90% |
| The product bug likely involves SQLite plugin version metadata during database pull. | Abduction | 85% | 65% |
| Any code fix is premature without repo access and reproduction. | Deduction | 99% | 95% |
| H1 merged detector/fallback hypothesis is the current best edge. | Abduction | 85% | 50% |
| Codex filtering is unavailable in this session. | Induction | 95% | 90% |

## Pruning Log

No product hypotheses pruned yet. H0 product behavior is not classified because perturbation access is blocked.

## Codex Filter

Attempted:

```sh
codex exec -
```

Result: failed before review with `failed to initialize in-process app-server client: Operation not permitted`. Per the investigation contract, surviving hypotheses are downgraded because codex filtering was unavailable. H1 remains open at 50% and must not be treated as confirmed.

## Provenance

- GitHub issue list observed `#3518` open on 2026-05-18 with title above and `Bug` label.
- Repository page observed `Automattic/studio` as public TypeScript/Electron WordPress Studio repo with latest release `v1.9.0` on 2026-05-11.
- WordPress Studio public changelog notes v1.5.6 upgraded Studio's SQLite plugin and enabled a new AST driver.
- Web search result from a public work-summary page mentions February 2026 work updating the SQLite plugin to `2.2.17` and reliability around `sqlite-command` files; this is secondary evidence only.
