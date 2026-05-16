# Bug Hunt (sonnet, round 7)

## Round 6 fixes verified

- **cli/pr_state.py `classify` → `scan` rename**: confirmed — the batch command is now `@pr_state_app.command("scan")` with function `pr_state_classify_run`. The single-PR command retains `@pr_state_app.command("classify")`. No naming collision. Typer sees two distinct command strings.
- **cli/inbox.py `triaged` in allowlist**: confirmed — `"triaged"` is in `valid = {"triaged", "investigate", "qa", "drip", "respondable", "retro"}` (line 66). `_inspect("triaged")` is reachable.
- **qa_actor.py dead `subprocess`/`time` imports dropped**: confirmed — neither import appears in the file. The workflow body uses only `workflow`, `temporalio`, and the qa activity imports.

## High severity (NEW)

### 1. `_acks.jsonl` and `_started.jsonl` are never written — inbox state model is broken

`inbox_state.inbox_states()` derives `queued / in_flight / done` buckets from three files:
- `<actor>.jsonl` — messages (written by `deliver_to_inbox`, `route_classified`, `deposit_issue_to_triaged`)
- `_started.jsonl` — which msg_ids are in-flight (never written)
- `_acks.jsonl` — which msg_ids are completed (never written)

A project-wide grep confirms: **no code in the codebase writes to `_acks.jsonl` or `_started.jsonl`.** Both files stay empty or absent. Consequences:

- `inbox_states(actor)["in_flight"]` is always `[]`
- `inbox_states(actor)["done"]` is always `[]`
- Every message ever deposited permanently appears in the `"queued"` bucket
- `punch.py` kanban shows 0 in-flight, 0 done across all actors — the live view is structurally wrong
- `board.py` likewise: all in-flight markers (✈️ prefix) are unreachable
- `sweep inbox <actor>` shows all messages as unacked forever

This affects every consumer of `inbox_states()`: `punch`, `board`, and `inbox`.

**Files**: `sweep/inbox_state.py` (read-only consumers) — the writer is missing from the entire codebase.

## Medium severity (NEW)

### 2. `PrStateWorkflow` never uses `deposit_classified` / `route_classified` — decoupled architecture not wired into Temporal

`worker.py` registers `deposit_classified` and `route_classified` as Temporal activities. But `PrStateWorkflow` (the only workflow that does PR classification) imports only `deliver_to_inbox` and calls it directly — it still uses the old coupled classify+deliver path.

The decoupled `scan` + `route` flow exists only in the CLI (`sweep pr-state scan`, `sweep pr-state route`). The automated/cron Temporal path bypasses it entirely. The documented benefit — "routing rule changes don't require re-classification" — is unavailable in the workflow path. `deposit_classified` and `route_classified` are dead weight in the worker activity registry.

**File**: `sweep/workflows/pr_state_workflow.py` (imports `deliver_to_inbox`, doesn't import or call `deposit_classified`/`route_classified`). `sweep/worker.py` registers them superfluously.

## Low severity / nits (NEW)

### 3. Stale docstrings for `cli/pr_state.py` and `cli/__init__.py`

- `sweep/cli/pr_state.py` line 1 docstring: `"classify, deliver, or run the Temporal workflow"` — omits `scan` and `route` commands added in rounds 5–6.
- `sweep/cli/__init__.py` line 5 comment: `"pr-state classify/run/workflow"` — same omission.

These are navigation references, not functional code. Low impact.

**Files**: `sweep/cli/pr_state.py` line 1; `sweep/cli/__init__.py` line 5.

### 4. `_render_outcomes` ZeroDivisionError when `--outcome-days 0`

`punch.py` line 238: `print(f"| daily merge rate | {merged / days:.1f} |")` — unguarded division. If `--outcome-days 0` is passed, `days = o["days"] = 0` and this raises `ZeroDivisionError`. The `ratio` guard on line 234 (for `total == 0`) does not cover the `days == 0` case. Requires deliberate misuse, low impact.

**File**: `sweep/cli/punch.py` line 238.

## Verified — not a bug

- **`_inspect("triaged")` end-to-end**: reads `triaged.jsonl`, dedupes by `msg_id`, loads global `_acks.jsonl` (empty → unacked set = all messages). Works correctly; shows all messages as unacked. Correct behavior given no writer for `_acks.jsonl` exists.
- **counters upsert first-insert race**: Two concurrent writers on a missing key — Writer A inserts `(key, n)`, Writer B hits `ON CONFLICT DO UPDATE SET value = value + excluded.value` = `n + n`. Both increments accumulate correctly. Not a bug.
- **`search_prs` `--state` injection**: `args[:-2] + ["--state", state] + args[-2:]` correctly inserts before `["--json", fields]`. Not a bug.
- **`gh_io.api` cache key non-determinism for prospect**: `path` includes URL-encoded query built from a fixed constant (`ACTIONABLE_LABELS` tuple). The label clause is always constructed in the same order. Cache key is deterministic.
- **`atomic_write_text` non-UTF-8 bytes**: only called with JSON or plain text strings (cursor, org state, attestation artifacts). `git diff` output (potential binary) is passed through `subprocess.run(..., text=True)` which decodes with the locale codec, not via `atomic_write_text`. Not a risk.
- **attestations `BEGIN IMMEDIATE` with locked DB**: `sqlite3.connect(..., timeout=10)` applies to all statement execution, not just the connection open. `BEGIN IMMEDIATE` will retry for 10s before raising `OperationalError`. The `except Exception: ROLLBACK; raise` path propagates cleanly.
- **`_render_outcomes` variable shadowing (`days`)**: `days = o["days"]` overwrites the parameter with the same value (guaranteed by `outcomes()` cache validation at `data.get("days") == days`). No logic error.
- **`skipped_acked` always 0**: pre-existing, flagged-not-fixed (rounds 3–6).
- **`qa_volley_hist` always `:1`**: pre-existing, flagged-not-fixed.
- **24h user TTL across auth switch**: pre-existing, flagged-not-fixed.
- **whitespace-only diff edge case**: pre-existing, flagged-not-fixed.
- **orphaned `search_issues` cache rows**: pre-existing, flagged-not-fixed.
