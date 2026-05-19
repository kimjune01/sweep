# Hypothesis Graph: NiklasRosenstein/pydoc-markdown#352

Re-investigation triggered by attest 2026-05-18T04:44 (post-hoc, after PR was opened 2026-05-11). Behavioral gate routed back because CI signal stayed red.

## H₀ — PR #352 CI is failing because of a code/test regression

- **Null:** CI fails for a reason unrelated to the fix's correctness (config, lint, infra).
- **Perturbation:** Read `gh pr view 352 --json statusCheckRollup`.
- **Observation:** Exactly one failing check: `"At least one new changelog entry must be added"` (Changelog workflow, `NiklasRosenstein/slap@gha/changelog/assert-added/v2`). All other checks SUCCESS. Mergeable=MERGEABLE, zero reviews, zero comments.
- **Trajectory shape:** **Divergent against H₀.** Failure is a process gate, not a code/test failure. No reviewer feedback, no logic bug surfaced.
- **Status:** Killed.
- **Edge:** The failing gate names the next hypothesis → H₁.
- **Mode:** Deduction (read the failing check name). Confidence: 99%.

## H₁ — The repo enforces a changelog entry per PR via `.changelog/_unreleased.toml`

- **Null:** The check is opt-in or there is an alternative (e.g., a `no changelog` label).
- **Perturbation:** Read `.github/workflows/changelog.yaml` and inspect the directory structure.
- **Observation:**
  - Workflow: `assert-added/v2` runs unless `no changelog` label is present.
  - `.changelog/_unreleased.toml` exists with five prior entries — each is a TOML `[[entries]]` table with `id` (UUID), `type` (feature / improvement / breaking change / fix / docs), `description`, `author`, `pr`.
  - PR #352's diff contains zero changelog files (`gh pr diff 352 --name-only`: only `markdown.py`, `main.py`, `test_duplicate_markdown_refs.py`).
- **Trajectory shape:** **Divergent for H₁.** Convention is documented, enforced by CI, schema is unambiguous.
- **Status:** Confirmed.
- **Edge:** Apply the convention → write an entry with `type=fix`, matching schema, fresh UUID.
- **Mode:** Deduction. Confidence: 99%.

## H₂ (provenance) — Is the missing changelog entry the only issue?

- **Perturbation:** `git log develop..HEAD` and `gh pr diff 352 --name-only`.
- **Observation:** PR contains **two** commits, not one:
  1. `89ee8fa` — `fix(cli): allow --bootstrap in projects with pyproject.toml` (issue #197, modifies `main.py`)
  2. `e6308a9` — `fix: uniquify markdown reference IDs to prevent conflicts (#125)` (issue #125, modifies `markdown.py` + test file)

  The PR body advertises only #125 (markdown refs). The bootstrap fix is silent scope creep.
- **Trajectory shape:** **Oscillatory** — the PR title/body claim one fix; the diff carries two. Maintainer may or may not flag it.
- **Status:** Noted, not addressed in this iteration.
- **Edge:** Could split into a separate PR for #197, or add a second changelog entry, or leave and let maintainer decide. **Following the "go with the flow" + "amend is low-risk only for body splices" rules: do not rewrite history without operator approval. Add one changelog entry for the documented fix; surface scope creep to operator.**
- **Mode:** Deduction. Confidence: 99% on observation, abductive on maintainer reaction.

## Graph state

| Node | Status     | Shape              | Mode      |
|------|------------|--------------------|-----------|
| H₀   | Killed     | Divergent against  | Deduction |
| H₁   | Confirmed  | Divergent for      | Deduction |
| H₂   | Open (deferred to operator) | Oscillatory | Deduction |

## Frontier

- **Scope creep (H₂):** PR includes 89ee8fa which addresses a different issue. Operator decision: (a) leave + add note in PR body, (b) split into separate PR via rebase + force-push (operator-gated). Recommend (a) — low cost, deferential to maintainer judgement.

## Fix applied

Added `.changelog/_unreleased.toml` entry:

```toml
[[entries]]
id = "61726e1f-3d36-4277-abc0-6923d6a7b0c1"
type = "fix"
description = "Uniquify Markdown reference-style link IDs across API objects to prevent collisions when multiple objects use the same numeric reference (e.g., `[text][0]`)"
author = "@kimjune01"
pr = "https://github.com/NiklasRosenstein/pydoc-markdown/pull/352"
```

Schema verified against five prior entries. UUID v4 freshly generated. `type=fix` matches the PR's nature.

## Provenance check

- **Origin of the changelog convention:** `.changelog/python.yml` and `changelog.yaml` workflows present in repo since at least 3.0.0; convention is stable.
- **Upstream issues/PRs around changelog:** none indicate the convention has changed.
- **Risk:** None — appending a well-formed entry is the maintainer-sanctioned path. The `Insert Pull Request URL into new changelog entries` workflow handles `pr =` rewriting if needed, but we set it correctly at write-time.
