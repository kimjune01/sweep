# cachix/devenv #2841 — zoxide: infinite loop detected (fish hook)

## H₀ — Observation

zoxide users with `--cmd cd` integration and the devenv fish hook installed
hit `zoxide: infinite loop detected` when `cd`-ing inside / out of a devenv
project. Multiple independent reports (pbek, dirkvdb, adiSuper94). Direnv
users are unaffected. The bash/zsh hooks are unaffected.

## H₁ — Root cause: `__zoxide_loop` env var leaks through `fish --no-config -c … devenv shell`

zoxide's fish init (`templates/fish.txt`) implements its loop guard as a
**single-shot env-var flag**, not a depth counter:

```fish
function __zoxide_cd
    if set -q __zoxide_loop
        builtin echo "zoxide: infinite loop detected"
        ...
        return 1
    end
    __zoxide_loop=1 __zoxide_cd_internal $argv
end
```

`__zoxide_loop=1 __zoxide_cd_internal $argv` is fish's "set VAR for this
command's environment" form. While `__zoxide_cd_internal` is on the stack,
`__zoxide_loop` is exported. `__zoxide_cd_internal` calls `builtin cd`,
which fires `--on-variable PWD` handlers **synchronously**. Devenv's
`_devenv_hook` is one such handler.

When `_devenv_hook` spawns its activation child:

```fish
fish --no-config -c 'cd -- $_DEVENV_HOOK_DIR; and devenv shell'
```

the child fish + the `devenv shell` Rust binary + the bash rcfile + the
final `exec fish -i -C "source devenv.fish"` all inherit `__zoxide_loop=1`
in their environment, because the parent's `__zoxide_cd_internal` frame
(which holds the var live) hasn't returned yet.

The innermost interactive fish loads `~/.config/fish/conf.d/zoxide.fish`,
which redefines `__zoxide_cd`. The user's first `cd` in that shell calls
`__zoxide_cd`, which sees `set -q __zoxide_loop` evaluate true (inherited
from env), prints "infinite loop detected", and bails — even though no
actual recursion has occurred.

**Provenance.** zoxide's flag has been a flag (not a counter) for years —
`__zoxide_loop` predates devenv's fish hook. Devenv's fish hook
(introduced in PR #2664, 2026-03-24) was modelled on direnv's, but direnv
uses `--on-event fish_prompt`, not `--on-variable PWD` — so direnv's child
spawns happen *after* the user's `cd` has returned, *after*
`__zoxide_loop` has been unset.

## H₂ — Why bash/zsh/posix are fine

`hook.bash-register.sh` and `hook.zsh-register.zsh` register `_devenv_hook`
on `PROMPT_COMMAND` / `precmd_functions`, which fire **after** the user's
`cd` returns. Any cd-wrapper-scoped env var is gone by then. The flaw is
fish-specific to the `--on-variable PWD` trigger.

## H₃ — Fix shape

Match the bash hook: move the activation work off `--on-variable PWD` and
onto `--on-event fish_prompt`, tracking PWD changes via a stored
`_DEVENV_HOOK_PWD` (mirroring the bash hook's existing `_DEVENV_HOOK_PWD`
guard). The on-cd-out `exit` from a hook-spawned inner shell still fires
correctly at the next prompt, before the user types anything.

## Trajectory: divergent — confirmed

- Mechanism is reproducible by inspection (zoxide template + devenv hook).
- Three independent user reports, all on fish + zoxide.
- Bash/zsh/posix unaffected (different trigger).
- Direnv unaffected (uses `fish_prompt`, not `--on-variable PWD`).

## Fix

`devenv/hooks/hook.fish`: replace `--on-variable PWD` with `--on-event
fish_prompt` + a `_DEVENV_HOOK_PWD` change guard. No behavioral change for
bash/zsh; cd-out exit still happens at next prompt fire inside the
hook-spawned shell.

Regression test: assert that an env var set in a fish "cd wrapper" frame
(`VAR=1 some_function_calling_builtin_cd`) is NOT visible to a subprocess
spawned by `_devenv_hook` during activation.

## Frontier edges

- None open. Two existing tests
  (`outer_shell_survives_cd_out`, `inner_shell_exits_on_cd_out`,
  `no_respawn_inside_devenv_shell`) continue to assert the existing
  invariants; a new test (`cd_wrapper_env_does_not_leak_to_activation_child`)
  covers the regression.
