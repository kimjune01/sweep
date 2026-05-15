# Bootstrap prompt — finish migration + live fixture test

Paste this into a fresh Claude Code session at `~/Documents/sweep` on branch `temporal-pipeline`. It's self-contained.

---

## Context

This is `kimjune01/sweep` — a Temporal-supervised PR pipeline rebuilt from a skills prototype. Branch `temporal-pipeline` has the new Python implementation; `master` has the old skill-only version.

The substrate is solid:
- `sweep/attestations.py` — SQLite + Merkle chain, tamper-evident, verified against live Haiku
- `sweep/gh_io.py` — SQLite-cached wrapper around `gh` CLI (TTL per endpoint)
- `sweep/llm_io.py` — content-hash cache + Anthropic SDK wrapper
- `sweep/fuses.py` — event-pinned attestation invalidation (head SHA, base SHA, review ID)
- `sweep/seen.py` — O(1) dedup for prospect
- `sweep/org_state.py` — front-of-pipe org gate
- `sweep/cli/punch.py` — cockpit (`sweep punch -w`)
- `sweep/cli/board.py` — 6-column kanban swim lanes
- `sweep/activities/{qa,pr_state,prospect}.py` — typed activities, postcondition asserts

What's not yet wired:
- `qa.codex_review` and `qa.gemini_review` are stubs that don't call `llm_io.call`
- `org_state.refresh`, `outcomes._query`, `prospect.gh_search_*`, `pr_state.gh_pr_view` still use `subprocess.run` directly instead of `gh_io`
- No fixture repo, no full-pipeline e2e test against real Haiku

## Tasks

### 1. Migrate remaining `subprocess.run(["gh", ...])` calls onto `gh_io`

In each module, replace direct `subprocess.run(["gh", …])` with the typed `gh_io` accessor. Files to migrate, in priority order (most-called first):

- `sweep/org_state.py` → `gh_io.search_prs(query, state="open", ttl=300)`
- `sweep/outcomes.py` → `gh_io.search_prs` with `--merged-at` / `--closed-at` filters (TTL 3600 since 1h cache already in place)
- `sweep/activities/pr_state.py` → `gh_io.pr_view(...)`, `gh_io.search_prs("author:@me state:open", ttl=60)`
- `sweep/activities/prospect.py` → `gh_io.search_repos(query, sort="stars", order="desc", ttl=600)`, `gh_io.search_issues(query, ttl=120)`

Acceptance: smoke-run each subcommand after each migration; expect identical output but fewer underlying gh subprocesses. `sweep attest gh-cache` shows the new endpoints populating.

### 2. Wire `qa.codex_review` and `qa.gemini_review` to `llm_io.call`

Right now these activities return canned strings. Replace with real LLM calls:

```python
# sweep/activities/qa.py

from sweep import llm_io, models

@activity.defn
async def codex_review(req: QaOneEntryRequest, diff: str) -> GateAttestation:
    model = models.default_for("adversary_1")  # codex; falls back via env override
    # In test mode, set SWEEP_MODEL_ADVERSARY_1=haiku to use Haiku as the adversary.
    result = await llm_io.call(
        model,
        system="You are a structural code reviewer. Verdict: pass / fail / revise.",
        user=f"Diff to review:\n\n{diff}\n\nVerdict + 1-paragraph reason.",
        msg_id=req.msg_id,
        repo=req.repo,
        pr=req.issue,
        max_tokens=300,
        temperature=0.0,
    )
    att = _capture(req.msg_id, "codex", result.response, worktree=req.worktree)
    att.verdict = _parse_verdict(result.response)
    att.provenance = f"{model.nick}{'-cached' if result.cached else ''}"
    return att
```

Same shape for `gemini_review`. The attestation log fills automatically; receipt path + sha256 already wired.

Acceptance: `scripts/e2e-haiku.py` still passes. Run `sweep qa codex --repo X --branch Y --worktree . --msg-id devtest` against a real repo; `sweep attest recent` shows the new row with a real `response_id` and nonzero tokens.

### 3. Build the live fixture test

Create the fixture repo manually (one-time, gh CLI):

```bash
gh repo create kimjune01/sweep-fixture --public --description "sweep e2e fixture: trivial todo app with known bugs"
cd /tmp && gh repo clone kimjune01/sweep-fixture && cd sweep-fixture
# Add a trivial Python todo app with a known-bad function
cat > todo.py <<'PY'
def add_todo(items, item):
    # BUG: off-by-one — appends N+1 times when called N times
    for _ in range(len(items) + 1):
        items.append(item)
    return items
PY
cat > test_todo.py <<'PY'
from todo import add_todo
def test_add_one():
    assert add_todo([], "a") == ["a"]
def test_add_two():
    assert add_todo(["a"], "b") == ["a", "b"]
PY
cat > pyproject.toml <<'PY'
[project]
name = "sweep-fixture"
version = "0.0.1"
requires-python = ">=3.10"
PY
git add . && git commit -m "initial fixture with known bug"
git push
```

Then write `scripts/e2e-fixture.py` that exercises the pipeline against it:

1. **Reset** — close all open issues/PRs on the fixture, force-reset main to a known SHA
2. **Inject** — open a known-title issue describing the bug
3. **Branch** — create `fix-{issue_number}` locally, apply a deterministic fix (replace `range(len(items) + 1)` with `# just append once`), commit
4. **Run qa** — call `qa_one_entry` against the branch with `SWEEP_MODEL_ADVERSARY_1=haiku` and `SWEEP_MODEL_ADVERSARY_2=haiku` so codex/gemini use Haiku as the test-fixture model
5. **Assert** — attestation rows exist with correct `msg_id`, `repo`, `pr`; `pinned_head_sha` matches `git rev-parse HEAD`; chain verifies; `fuses.check_qa_bundle` returns `(False, ...)` for current SHA
6. **Tamper** — `git commit --allow-empty -m "advance head"`; re-check fuses; expect `(True, ['head SHA changed...'])`
7. **Cleanup** — close the issue, delete the local branch, reset fixture main

Reference pattern from `scripts/e2e-haiku.py` — same `check()` helper, same color-coded staging, same exit-1-on-fail.

Acceptance: `ANTHROPIC_API_KEY=… uv run python scripts/e2e-fixture.py` runs end-to-end against real Haiku + real GitHub, every assertion green, fixture left in a clean state.

## Style

- Commit messages: short subject (lowercase, area-prefix), 1-2 paragraph body explaining *why*. Match existing log: `git log --oneline -10`.
- One commit per logical chunk; don't bundle migrations of different files into one commit.
- Don't add high-volume or load-style tests — production catches those. Tests prove substrate correctness with the smallest live workload that exercises each path.
- Don't roleplay reviewers or add affirmation language. Push back where the spec is wrong.

## Done = green

When all three tasks are complete:
- `sweep attest gh-cache` shows every endpoint we migrated
- `scripts/e2e-haiku.py` still passes
- `scripts/e2e-fixture.py` passes against live GitHub + live Haiku
- `git log --oneline temporal-pipeline ^master` shows clean per-step commits
