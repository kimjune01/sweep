---
name: qa
description: Adversarial code review — codex (structural) and gemini (logic) volley until convergence or budget. Advances triaged entries to qa_passed with gate attestations. WIP=1, takt 5 min.
argument-hint: <repo> [--entry BRANCH] [--budget SECONDS] [--dry-run]
allowed-tools: Read, Write, Edit, Bash, Glob, Skill
---

# QA: Adversarial Code Review

Run codex and gemini as adversarial reviewers on a triaged branch. Produce gate attestations that `/drip` and `/ship` consume downstream. The skill is the volley operator on a single drip-queue entry.

## Monoidal contract

| Input | Output | Valid alone? |
|-------|--------|--------------|
| Drip-queue entry with `status: "triaged"`, branch + test attached | Same entry advanced to `status: "qa_passed"` with `gates: {…}`, or kept at `triaged` with a `qa_failed` audit record | Yes — single-entry adversarial review |

**Identity:** qa on an entry that already has complete gates is a no-op. The status doesn't change, no new lines are appended.

**Composition:** `qa(qa(x)) == qa(x)`. Fixed-point under repeated application — second call sees gates already present, returns immediately. This is the OTP-kanban invariant: any tick may re-fire /qa on any entry without producing duplicate work or churn.

**Preconditions:** `/triage` produced a branch with a failing-on-master / passing-on-fix test. `gh auth status` passes. `/codex` and `/gemini` are installed (qa is a coordinator — codex and gemini do the actual review).

## OTP-kanban semantics

Each `/qa` invocation is one **takt** at 5 minutes. WIP=1: process at most one entry per call. The pipeline tick is the scheduler — it fires `/qa` per repo per takt.

| Phase | Budget |
|-------|--------|
| Pick the next `triaged` entry (oldest first) | < 5 s |
| Run codex volley (≤3 rounds) | ~2 min |
| Run gemini volley (≤3 rounds) | ~2 min |
| Write gates + advance status | < 10 s |
| **Total** | **~5 min hard cap** |

If the budget runs out mid-volley, append a `qa_partial` audit record with the rounds completed, keep status at `triaged`. The next takt picks up where this one left off (each round's verdict is appended; the resume reads the latest verdict).

WIP=1 means: do not parallelize across entries in one invocation. If you want N entries reviewed per takt, the scheduler fires `/qa` N times. This keeps the org-gate, banlist, and cooldown checks coherent per-entry.

## Input

- `<repo>` — `owner/repo`. Required. Single-repo per invocation (same contract as `/triage`, `/drip`).
- `--entry BRANCH` — operate on a specific entry. Defaults to the oldest `triaged` entry without complete gates.
- `--budget SECONDS` — override the 300 s default (e.g. `--budget 600` for hard cases). The 5-min default matches the pipeline takt; longer budgets break the kanban rhythm.
- `--dry-run` — run codex + gemini, print verdicts, but do not append to the drip queue. Use to inspect a contentious entry without mutating state.

## State

`~/.sweep/drip-queue/<owner>-<repo>.jsonl` — append-only, same file `/triage` and `/drip` use.

**Read (current state of an entry):** parse all lines, key by `branch`, take last entry per key.

**Triaged entry (input to qa):**
```jsonl
{"ts":"...","action":"enqueue","branch":"fix-3362","issue":3362,"test_cmd":"pytest tests/test_x.py","worktree":"/Users/junekim/Documents/click","status":"triaged"}
```

**qa_passed entry (output):**
```jsonl
{"ts":"...","action":"qa","branch":"fix-3362","status":"qa_passed","gates":{"bugs_found":0,"gemini_first":"pass","gemini_last":"pass","gemini_rounds":2,"codex_verdict":"pass","codex_rounds":1,"test_attestation":"pass"}}
```

**qa_failed entry (terminal — surfaced to human, not retried automatically):**
```jsonl
{"ts":"...","action":"qa","branch":"fix-3362","status":"qa_failed","gates":{"bugs_found":2,"gemini_last":"reject","codex_verdict":"reject","test_attestation":"pass"},"reason":"gemini found inverted condition on line 47; codex flagged missing edge case"}
```

**qa_partial (budget exhausted, will resume next takt):**
```jsonl
{"ts":"...","action":"qa","branch":"fix-3362","status":"triaged","partial":{"gemini_rounds":2,"codex_rounds":0,"elapsed":287}}
```

## Process

### 1. Preflight

1. `gh auth status` — fail fast.
2. Read `~/.sweep/drip-queue/<owner>-<repo>.jsonl`. Build the per-branch latest-state map.
3. **Idempotence check.** If the target entry already has `status: "qa_passed"` with all five gate fields populated, exit 0 with `"already qa'd"`. No new line appended.
4. **Pick the entry.** Default: oldest `triaged` entry whose latest record lacks `gates.bugs_found` (an integer). If `--entry` is set, use it; if it's not `triaged`, refuse.
5. **Worktree check.** The entry's `worktree` path must exist and the `branch` must be checked out (or checkoutable). If not, append `qa_failed` with `reason: "worktree missing"`. Don't volley.

### 2. Test attestation (hard gate, runs first — cheap)

Before paying for codex/gemini tokens, confirm the test claim.

1. `cd <worktree>`, checkout default branch, run `<test_cmd>`. Must **fail**. If it passes: `gates.test_attestation = "fail_on_master"`, append `qa_failed`, exit.
2. Checkout `<branch>`, run `<test_cmd>`. Must **pass**. If it fails: `gates.test_attestation = "fail_on_fix"`, append `qa_failed`, exit.
3. On success: `test_attestation = "pass"`.

The test attestation is the cheapest gate. Running it first means a broken test never spends adversarial-review tokens.

### 3. Codex volley (structural)

Send the diff + the issue body + relevant file contents to `/codex` with this framing:

> Review this fix as a maintainer of `<repo>` seeing it for the first time. Find structural problems: missing edge cases, wrong abstractions, scope creep, hidden coupling, missed invariants. Don't comment on style. Verdict: `pass` / `reject` / `revise`. If `revise`, list specific changes.

**Round loop:**
- Round 1: send the diff. Capture `verdict_1`.
- If `verdict_1 == "pass"`: `codex_rounds = 1`, `codex_verdict = "pass"`, done.
- If `verdict_1 == "revise"`: apply the requested changes (Edit / Bash, then re-commit on the same branch with `--amend` or a fixup commit). Re-run the test (test_attestation must still hold). Re-send the new diff. Repeat up to 3 rounds.
- If `verdict_1 == "reject"`: `codex_verdict = "reject"`, `codex_rounds = 1`. Continue to gemini anyway — its trace may add bug count. Don't fix.

**Convergence:** stop when `verdict_n == "pass"` or `n == 3` or budget per phase exhausted (~2 min). Record the final verdict as `codex_verdict`.

### 4. Gemini volley (logic)

Same shape, different framing:

> Trace the logic in this diff. Find: inverted boolean conditions, off-by-one errors, missed branches, race conditions, type confusions. The fix must be correct, not just plausible. Verdict: `pass` / `reject` / `revise`.

Same round loop and convergence as codex. Record `gemini_first` (round 1 verdict) and `gemini_last` (final verdict). Both fields are required by the gate-pr-create.sh hook downstream — `gemini_first` proves we sent it, `gemini_last` proves we converged.

### 5. Tally bugs

`bugs_found` is the count of distinct bugs that either reviewer identified across all rounds. A bug fixed in round 2 still counts as one bug found. This number is the cheapest signal for the retro pass — if `bugs_found` correlates with downstream rejection, the pipeline learns to demand more rounds.

The tick.py demoter checks `isinstance(gates.bugs_found, int)` — so `bugs_found` must always be present and an integer (including 0). A missing key sends the entry back to `queued`.

### 6. Verdict and append

| Both verdicts | Action |
|---------------|--------|
| `pass` and `pass` | Append `qa_passed` with full gates. Status: `qa_passed`. |
| `pass` and `reject` (either order) | Append `qa_failed` with the rejecting reviewer's reason. Surface to human. |
| `reject` and `reject` | Append `qa_failed`. Surface to human — the fix is likely wrong, not just polished. |
| Either `revise` after 3 rounds without convergence | Append `qa_failed` with `reason: "volley did not converge in 3 rounds"`. Surface. |

Never auto-advance a `qa_failed` entry. The human triages it — usually by editing the branch and re-running `/qa`, or by killing it via `/drip --kill`.

### 7. Budget exhaustion

If the 5-min budget expires before both volleys complete:
- Append `qa_partial` with the rounds completed in each phase.
- Leave status at `triaged` — the next takt will resume.
- The resume logic in step 1 must read the latest `qa_partial` for the branch and skip phases already complete in that record.

This is the OTP recovery story: a crashed/timed-out actor leaves a partial record; the supervisor (the tick) re-fires; the next actor reads the partial and finishes.

## Volley rules

- **Both reviewers see the same diff.** Don't shape the prompt to one model's strengths. The point of two reviewers is independent blind spots.
- **`/codex` and `/gemini` are skills, not models.** Call them via the Skill tool. If `/gemini` is stubbed (no subscription), `qa` skips gemini and records `gemini_first = "stubbed"`, `gemini_last = "stubbed"`. The downstream hook will block the PR — that's correct behavior. The user unstubs or removes the entry.
- **Codex credit fallback.** If `/codex` returns a credit/quota error (or is otherwise unavailable), fall back to an Opus subagent playing the structural-reviewer role. Spawn via `Agent(subagent_type: "general-purpose", model: "opus")` with the same framing prompt codex would have received. Record the verdict as `codex_verdict` (the slot, not the producer) and add `codex_provenance: "opus-fallback"` to the gates object so the retro can separate real-codex outcomes from fallback outcomes. The downstream hook doesn't care about provenance — only that `codex_verdict` is populated. Codex credits restore 2026-05-17; remove the fallback path after the retro confirms it tracks codex's verdicts closely enough.
- **Apply codex's `revise` suggestions; surface gemini's `revise` suggestions.** Codex is better at structural rewrites; auto-applying its diffs converges. Gemini is better at logic traces; its `revise` notes go into the audit record for the human, not auto-applied. (If this changes after the retro, update this rule.)
- **Never edit the diff to satisfy a reviewer if doing so changes the issue's intent.** If a reviewer asks for a change that the issue's commenter didn't ask for, surface to human. The volley shapes the fix, not the goal.
- **No PR description in qa.** Descriptions are a `/drip` concern. qa produces attestations; drip writes the description from the gate file at push time.

## Rules

- **WIP=1.** One entry per invocation. Sweep's `--pipeline` tick fires `/qa` per repo per takt to scale throughput.
- **Idempotent.** `qa(qa(x)) == qa(x)`. Repeated invocations with complete gates are no-ops.
- **No `gh pr create`.** Ever. The gate-pr-create.sh hook will block it anyway. Ship is the only path to PR creation.
- **Append-only.** Never edit prior lines in the drip-queue jsonl. State derives from the latest line per branch.
- **Auth first.** `gh auth status` before any other work.
- **Hard budget.** 5 min default. Override only for explicit user requests, not for "this one's tricky" rationalization.
- **Test attestation first.** Don't pay for adversarial review until the test claim is verified.

## Failure modes

- **Worktree missing / branch un-checkoutable:** `qa_failed`, reason recorded, no volley run. The triage agent will need to rebuild the worktree.
- **Test passes on master:** `qa_failed`, `test_attestation = "fail_on_master"`. The bug was already fixed upstream — likely a staleness issue triage should have caught.
- **Test fails on fix:** `qa_failed`, `test_attestation = "fail_on_fix"`. The fix is broken — surface to human.
- **`/codex` or `/gemini` errors (rate limit, API down):** Append `qa_partial` with the verdicts collected so far. Don't fail the entry. Retry on the next takt.
- **`/gemini` stubbed:** Record `gemini_first = "stubbed"`, `gemini_last = "stubbed"`, `bugs_found = <codex's count>`. The hook will block downstream — that's the contract.
- **Volley non-convergence in 3 rounds:** `qa_failed` with `reason: "did not converge"`. Surface — usually means the fix has a real ambiguity the reviewers disagree on.
- **Budget exhausted mid-volley:** `qa_partial`, status stays `triaged`, resume next takt.

## Standalone use

The drip-queue jsonl is the interface. Any process that appends a valid `qa_passed` line with complete gates can substitute for `/qa` — manual review, an external CI signal, a different reviewer combination. The downstream hook only checks the gate fields, not the producer.

That's the OTP invariant: stages communicate through an append-only log, not direct calls. Replace any stage without telling the others.
