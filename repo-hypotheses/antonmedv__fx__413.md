# Hypothesis Graph: antonmedv/fx#413

Target: antonmedv/fx issue #413, "Yank doesn't work with snap"
Date: 2026-05-18
Mode: standalone investigate, halted at Phase 1 because perturbation access is missing.

## Environment

`sweep project-info antonmedv/fx`:

```json
{
  "repo": "antonmedv/fx",
  "worktree": "/Users/junekim/.sweep/worktrees/antonmedv__fx",
  "worktree_exists": false,
  "test_env": "docker:sweep-tester:latest",
  "test_cmd": null,
  "test_setup_cmd": null,
  "notes": [
    "test_env defaulted to sweep-tester image"
  ]
}
```

Local constraints:

- Cannot create the canonical worktree under `/Users/junekim/.sweep/worktrees`: sandbox denies writes there.
- Cannot clone into the workspace-local fallback path: shell DNS cannot resolve `github.com`.
- `gh issue view 413 --repo antonmedv/fx` cannot reach `api.github.com`.
- No local `fx` binary is installed.
- No local snap runtime/Ubuntu snap confinement environment is available.

Perturbation access status: blocked. The system cannot be poked locally, so the graph cannot progress beyond cached observation and provisional abduction.

## Issue Evidence

Cached triage record in `repo-hypotheses/antonmedv-fx.md`:

| # | Title | State | Score | Effort | Signal | Status |
|---|---|---|---|---|---|---|
| 413 | Yank doesn't work with snap | OPEN | 3/10 | Docs only | Snap environment limitation | SKIP |

No fresh issue body or comments were available from the local shell. GitHub web search did not surface the issue body.

## Blind-Blind Merge

### Hypothesis A

Root cause: `fx` yank/copy depends on host clipboard access. The snap package runs under snap confinement, so either the clipboard interface is not declared/connected or the package cannot execute the host clipboard helper it expects.

Fix shape: likely not a Go code fix in `fx` itself unless the snap manifest is missing a clipboard interface. First classify whether this is packaging metadata (`snapcraft.yaml` plugs) or an unavoidable confinement limitation. If unavoidable, document snap-specific limitations and recommend a non-snap install for yank.

Evidence trajectory: abduction from the issue title plus cached triage. No direct measurement.

Confidence: 60%, capped by missing issue body/source/snap env.

### Hypothesis B

Root cause: `fx` yank/copy likely shells out to host clipboard mechanisms such as `xclip`, `xsel`, `wl-copy`, or `pbcopy`, or opens clipboard-related sockets that a strictly confined snap cannot see. Snap may filter/remap GUI/session resources, `$PATH`, `$XDG_RUNTIME_DIR`, Wayland/X11 sockets, and host binaries.

Fix shape: treat as a snap packaging limitation unless code evidence proves otherwise. Add install/troubleshooting documentation that snap clipboard yank may not work under confinement and recommend non-snap installs for clipboard support. If snap metadata is maintained in-repo, inspect/add relevant plugs such as `x11`, `wayland`, and desktop/session interfaces, plus any required `snap connect` instructions.

Concrete perturbations:

- Reproduce yank under snap and capture whether it silently fails, reports missing clipboard commands, or hits access denial.
- Compare with a non-snap install on the same machine/session.
- Inspect the yank implementation and clipboard backend lookup order.
- Inspect snap metadata and test under X11 and Wayland.
- From `snap run --shell fx`, test `which xclip xsel wl-copy` and direct clipboard writes if possible.

Confidence: 60% abduction, capped by missing source, snap metadata, and issue body.

### Where A and B Diverge

No material divergence. Both passes point to snap confinement or snap packaging metadata as the likely cause. B emphasizes host clipboard command/socket visibility and X11/Wayland split testing; A emphasizes the branch between packaging fix and documentation-only.

Downstream implication: do not implement a code change until the snap package behavior is reproduced and the snap manifest/source path is inspected.

## Graph State

| Node | Status | Shape | Summary |
|---|---|---|---|
| H0 | partial | unclassified | Cached observation says yank fails only under snap; no local reproduction possible. |
| H1 | open | predicted divergent | Snap confinement blocks clipboard access or clipboard helper execution. |
| H2 | open | predicted convergent or divergent | Snap packaging may be missing a clipboard-related interface that can be declared/connected. |
| H3 | open | predicted convergent | If confinement is intentional/unavoidable, a docs/install note is the correct fix shape. |

## Nodes

### H0: Baseline observation

Hypothesis: `fx` installed from snap should support yank/copy the same way as other install methods.

Null: Snap installation has a known confinement limitation, so yank cannot be expected to behave like Homebrew/go-install/native packages without extra interface permissions.

Perturbation:

```sh
snap install fx
printf '{"a":1}\n' | fx
# enter interactive mode and trigger the yank key path from the issue
```

Trajectory:

- Cached triage sample: issue #413 is open and titled "Yank doesn't work with snap".
- Cached triage interpretation: "Snap environment limitation", "Docs only", "SKIP".
- Local sample: not run; no checkout, no binary, no snap runtime, no network clone.

Shape: unclassified/partial. The observation is plausible but not measured in this environment.

Kill condition: a snap-installed `fx` can yank successfully under a clean Ubuntu snap environment, or the issue body shows a non-snap-specific failure mode.

Edge: classify snap clipboard confinement versus packaging manifest omission.

Reasoning mode: induction from cached triage, confidence 55%.

### H1: Snap confinement blocks clipboard access

Hypothesis: yank fails because the snap package cannot access the desktop clipboard or cannot spawn/access the clipboard helper used by `fx`.

Null: Snap confinement permits clipboard access, and the failure is instead an `fx` keybinding/copy-path bug or a missing packaging interface.

Perturbation:

1. Inspect the yank implementation in the checkout.
2. Inspect snap packaging metadata for declared plugs/interfaces.
3. In an Ubuntu snap environment, run `snap connections fx` and reproduce yank.
4. Compare with a native `go install github.com/antonmedv/fx@latest` binary on the same host.

Predicted shape: divergent if native yank works and snap yank fails with confinement or helper-access errors.

Kill condition: snap logs show the yank code path is not reached, or native install fails identically.

Edge: if confirmed, split into H2 packaging fix versus H3 documentation-only.

Reasoning mode: abduction, confidence 60%.

### H2: Snap package is missing a connectable clipboard interface

Hypothesis: the snap manifest can be changed to declare the needed desktop/clipboard interface, making yank work after install or after `snap connect`.

Null: the needed access is unavailable to strict snaps or already declared, so packaging metadata is not the fix.

Perturbation:

```sh
snap connections fx
snap info fx
snap run --shell fx
```

Then inspect and patch the repo's snap metadata if present.

Predicted shape: convergent if the missing interface is obvious but requires manual connection; divergent improvement if adding the interface makes yank pass in a snap-built test package.

Kill condition: interface is already declared/connected, or snap policy cannot grant the needed access for this CLI behavior.

Reasoning mode: abduction, confidence 50%.

### H3: Documentation/install note is the proper fix

Hypothesis: snap confinement makes yank unreliable or unsupported, so the appropriate contribution is documentation: warn that snap builds do not support yank/clipboard and recommend Homebrew, package manager, or `go install` when clipboard support is required.

Null: a small packaging metadata change can restore yank, making docs-only insufficient.

Perturbation:

Inspect existing install docs and README package sections, then compare maintainer conventions for documenting install-specific caveats.

Predicted shape: convergent only if H1 is confirmed and H2 is killed.

Kill condition: a working snap packaging fix is demonstrated.

Reasoning mode: abduction, confidence 50%.

## Frontier Edges

| Edge | Experiment | Predicted classification | Priority |
|---|---|---|---|
| H0 -> H1 | Reproduce yank under snap and native install on the same Ubuntu host | divergent | high |
| H1 -> H2 | Inspect `snapcraft.yaml`/snap metadata and `snap connections fx` | divergent or convergent | high |
| H1 -> H3 | If snap access is not fixable, inspect docs/install conventions for a minimal caveat | convergent | medium |
| H2 -> fix | Build/install patched snap package and retry yank | divergent improvement | medium |

## Reasoning Modes

| Claim | Mode | Confidence |
|---|---|---|
| Issue #413 is about yank failure in snap | induction from cached triage | 55% |
| Snap confinement is the likely cause | abduction | 60% |
| A packaging interface may fix it | abduction | 50% |
| Docs-only may be the correct output | abduction from cached triage | 50% |
| No PR-ready diagnosis exists in this environment | deduction from failed local access attempts | 95% |

## Pruning Log

No hypotheses pruned. Required perturbations are unavailable.

## Provenance

Not completed. Required commands are blocked by missing checkout/network/snap environment:

- `git blame` around yank implementation and snap packaging metadata.
- GitHub issue/PR search for `snap`, `yank`, `clipboard`.
- Existing PR idempotency guard.

Available provenance:

- Cached Sweep triage on 2026-05-09 marked #413 open, low score, docs-only, likely snap environment limitation.

## Current Halt

Status: blocked before Phase 1 measurement.

Reason: perturbation access is required. This environment has neither a checkout nor a runnable snap/native `fx` setup, and shell network access cannot fetch them.

Next resumption step:

1. Provide a writable checkout of `antonmedv/fx` or allow the canonical worktree to be created.
2. Re-run `sweep project-info antonmedv/fx`.
3. Reproduce yank under snap and native install on the same Ubuntu host.
4. Classify H1/H2/H3 before making any code or docs change.
