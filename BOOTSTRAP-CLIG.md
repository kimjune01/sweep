# Bootstrap — clig.dev ergonomics pass

Paste this into a fresh Claude Code session at `~/Documents/sweep` on branch `temporal-pipeline`. Self-contained.

---

## Context

`kimjune01/sweep` is a Temporal-supervised PR pipeline. The CLI surface is built with Typer and has grown organically over several rounds — substrate-correct but ergonomically inconsistent. This pass aligns it with the [Command Line Interface Guidelines](https://clig.dev) without changing semantics.

Current command surface (after `temporal-pipeline` ahead-of-master work):

```
sweep
├── qa         (test / codex / gemini / full; actor signal/status/clear)
├── pr-state   (classify / run / scan / route / workflow)
├── prospect   (sweep / cursor)
├── inbox      (one actor argument, dedup-by-msg_id read)
├── attest     (verify / recent / for-msg / tokens / gh-cache / gh-purge)
├── observe    (counters / events / cursor / advance)
├── retro      (list / status / show / discard / record)
├── punch      (cockpit + outcomes, -w live mode)
├── board      (kanban swim lanes)
└── models     (model registry summary)
```

Use `uv run sweep <subcommand> --help` to enumerate per-subcommand options. The Typer app lives at `sweep/cli/__init__.py` with one module per subgroup at `sweep/cli/<name>.py`.

## Tasks

The clig.dev sections to apply, in priority order:

### 1. Help text discipline

Every command needs:
- A one-sentence summary in the docstring (already mostly present).
- An **examples** block visible in `--help` output. Add via the typer `epilog` parameter or in the docstring.

Acceptance: `sweep <any> --help` shows at least one realistic example.

### 2. Consistent exit codes

Adopt the trio:
- **0** — success
- **1** — expected runtime error (cap reached, gh not authed, file missing)
- **2** — misuse (bad flag, missing required arg — already typer's default)

Audit each subcommand. `raise typer.Exit(code=N)` is the mechanism; default 0 is fine for success. Replace any bare `sys.exit(1)` with `typer.Exit(1)` for consistency.

Acceptance: `sweep retro record --subjective ... --plan ...` (missing flags) exits 2; cap-reached exits 1; success exits 0. Same shape across all subcommands.

### 3. Output stream separation

- **stdout**: data the user might pipe (json, jsonl, tables, single values)
- **stderr**: progress, warnings, error messages, summary lines a script wouldn't parse

Current behavior: everything goes to stdout via `print(...)`. Update the **summary lines** in `record`, `discard`, etc. to write to stderr (e.g. `print(..., file=sys.stderr)`) so pipes only see data.

Acceptance: `sweep retro list 2>/dev/null` shows only the pending retros; `sweep retro record ... 2>/dev/null` writes the round and emits nothing on stdout.

### 4. `--json` flag for machine output

Where the current default is human-friendly rendering, add a `--json` flag that emits a single JSON document on stdout. Apply to:

- `sweep retro list` — current is two-column text; `--json` emits `[{"name", "written_at"}]`
- `sweep retro status` — current is one-line text; `--json` emits `{"count", "cap", "halted"}`
- `sweep observe counters` — current is aligned text; `--json` emits the dict
- `sweep observe cursor` — current is two lines; `--json` emits `{"offset", "unread"}`
- `sweep attest tokens` — already JSON; just verify the contract
- `sweep attest gh-cache` — already JSON; verify

Acceptance: `sweep retro list --json | jq` works for every flagged subcommand.

### 5. Confirmation prompts for destructive ops

Destructive commands prompt before acting unless `--yes` (or `-y`) is passed. Apply to:

- `sweep retro discard` — already silent. Add prompt unless `--yes`.
- `sweep attest gh-purge` — currently silent. Add prompt unless `--yes`.
- `sweep observe advance` — already requires `--yes`; verify the message is clear.

Acceptance: bare `sweep retro discard <slug>` prompts "discard <slug>? [y/N]"; with `--yes`, no prompt.

### 6. Respect `NO_COLOR`

If the env var `NO_COLOR` is set (any non-empty value), suppress ANSI color codes in output. Check `sweep punch`, `sweep board`, any rich-rendered subcommand. Typer's `rich_help_panel` and similar should also degrade.

Acceptance: `NO_COLOR=1 sweep punch | cat -A` shows no escape sequences.

### 7. Tab completion install

Typer supports `--install-completion` natively at the top-level. Verify it works:

```
uv run sweep --install-completion zsh
```

Acceptance: a fresh shell tab-completes `sweep <TAB>` to the registered subcommand list.

### 8. Version flag

Add a top-level `--version` flag that prints the sweep package version and exits 0.

Acceptance: `sweep --version` shows something like `sweep 0.0.1` (read from `pyproject.toml` via `importlib.metadata.version("sweep")`).

### 9. Quiet flag

A top-level `-q / --quiet` flag that silences stderr progress/summary output. Useful for cron jobs that already capture stdout.

Acceptance: `sweep -q retro record ...` writes the file but emits nothing.

### 10. Misuse vs error distinction in messages

- Misuse (bad input from user): one-line message, no traceback.
- Internal error (bug or unexpected state): one-line message plus traceback to stderr.

Set `pretty_exceptions_enable=False` already in `cli/__init__.py`; verify the experience and tighten messages where the Typer default leaks too much (e.g. `BadParameter` should print a sentence, not a `Usage:` block).

## Out of scope

- Renaming commands (`scan` vs `classify` already happened in the bug-hunt round).
- Substrate changes (retro_state, observe, gh_io). This pass is CLI-only.
- The cockpit (`sweep punch -w`) layout — leave as-is unless `NO_COLOR` work touches it.
- Tests/e2e — they pass currently; the ergonomics changes shouldn't break them, but no new tests needed.

## Style

- Commit messages: lowercase subject, area-prefix, short. Match `git log --oneline -10`.
- One commit per clig.dev section. Easy to audit; easy to revert one without losing the others.
- Don't add abstractions for "future flexibility." If a feature isn't requested, don't build it.
- Don't roleplay or add affirmation. Push back where the spec is wrong.

## Done = green

When all sections are addressed:
- `sweep <any> --help` shows an example for every command.
- Exit codes are consistent across subcommands.
- stdout/stderr are split cleanly (`2>/dev/null` doesn't strip data).
- `--json` works on the listed read commands.
- Destructive ops prompt unless `--yes`.
- `NO_COLOR=1` produces uncolored output.
- `sweep --version` works.
- `sweep -q` silences non-essential output.
- `git log --oneline temporal-pipeline ^master | grep -i clig` shows the cluster of clean per-step commits.
