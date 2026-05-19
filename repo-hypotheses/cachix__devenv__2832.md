# cachix/devenv#2832 — AutoActivation: Checking out old branches breaks pre-commit

## H₀ (observation)

When `devenv activate` re-runs after a `git checkout` to a branch with a different `devenv.lock`, subsequent `git commit` fails with:

```
[INTERNAL] Pre-commit script is installed in migration mode...
run `pre-commit install -f --hook-type pre-commit` to fix this.
```

The error message names the remedy: re-install with `-f` (overwrite).

## H₁ (root cause, confirmed)

The `devenv:git-hooks:install` task in `src/modules/integrations/git-hooks.nix` invokes `prek install -c <configPath>` **without `-f`**. The companion `files.${configPath}.source = cfg.configFile` block at line 183 always rewrites the YAML config when the lock/derivation changes, but the hook script in `.git/hooks/pre-commit` carries an embedded fingerprint that prek/pre-commit refuses to overwrite without `-f`.

So on branch switch:
- YAML config: refreshed (files API)
- Hook script fingerprint: stale (install task silently no-ops)
- Mismatch → "migration mode" → commits blocked

Perturbation: read the file. `src/modules/integrations/git-hooks.nix:153,161,164` — three `install` call sites, none pass `-f`. The user-facing remediation in the issue is `pre-commit install -f --hook-type pre-commit`. **Trajectory: divergent confirm.**

### Provenance

- File has only two commits in the shallow clone (`2d97af8`, `9486594`); neither touches the install task. The missing `-f` is a long-standing inherited default, not a deliberate choice with a documented rationale.
- prek (the new default `pkgs.prek`, switched 2026-02-02) is a drop-in pre-commit replacement; `-f`/`--overwrite` has identical semantics: "Overwrite existing hooks / remove migration mode."
- No prior issue/PR on `cachix/devenv` mentions "migration mode" or "prek install -f" (gh search). First report.

## H₁ₐ (alternative, killed)

*Hypothesis: the install task isn't running on re-activation, so adding `-f` is irrelevant.*

Killed by reading the task definition: `after = [ "devenv:files" ]; before = [ "devenv:enterShell" ]`. It runs every shell entry. The user explicitly says "auto-activate will attempt to update the pre-commit hooks but will not error" — the task runs, it just doesn't overwrite.

## H₂ (cowardly hooksPath, separate issue, not fixed here)

The follow-up comment shows a second failure when the user manually runs the recommended `pre-commit install -f`:

```
[ERROR] Cowardly refusing to install hooks with `core.hooksPath` set.
```

This is environment-specific (user has `core.hooksPath` set globally or via another tool, e.g. lefthook, husky, or worktree config). Out of scope — devenv's install task hits the same condition only if the user's git config has hooksPath. The primary issue (#2832 body) is the migration-mode bug, which is fixed by `-f`. Note this in the PR but don't try to overrule pre-commit's safety check.

## Fix

Add `-f` (`--overwrite`) to all three `prek install` call sites:

```diff
-                ${executable} install -c ${configPath}
+                ${executable} install -f -c ${configPath}
...
-                      ${executable} install -c ${configPath} -t "pre-$stage"
+                      ${executable} install -f -c ${configPath} -t "pre-$stage"
...
-                      ${executable} install -c ${configPath} -t "$stage"
+                      ${executable} install -f -c ${configPath} -t "$stage"
```

Three-line change in `src/modules/integrations/git-hooks.nix`.

## Reasoning mode

| Claim | Mode | Confidence |
|-------|------|------------|
| Install task lacks `-f` | Deduction (read source) | 99% |
| `-f` resolves migration-mode mismatch | Deduction (pre-commit's own remedy message) | 95% |
| Adding `-f` is safe (idempotent overwrite) | Deduction + induction (documented prek/pre-commit behavior) | 90% |
| Fixes user's reported symptom | Abduction → deduction | 90% |
| The "cowardly" follow-up is in scope | — | killed (out of scope) |

## Frontier

- None open. Single-cause diagnosis, single-line fix per call site.
- Behavioral test in devenv's test harness would require nix infra to reproduce branch-switch fingerprint drift — skipping; the change is mechanical and matches the user-recommended remedy verbatim.
