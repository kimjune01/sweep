# microsoft/aici#122 — Fix non-deterministic backtracking in pyctrl

**PR (ours):** https://github.com/microsoft/aici/pull/122 — author kimjune01, opened 2026-05-10
**Issue addressed:** [#93 pyctrl backtracking is non-idempotent](https://github.com/microsoft/aici/issues/93), reporter `matthai`, 2024-04
**Repo state:** dormant since 2025-01-22 push; last PR merge was #118 on 2024-11-10
**CI:** build job RED on `wasm32-wasi` (renamed to `wasm32-wasip1` upstream) — environmental, not our code
**Reviews:** none

---

## H₀ — "The fix solves the reported bug"

**Claim (from PR body):** `LogitsProcessor::new` was calling `StdRng::from_entropy()`, so every constructor produced a different seed; replacing with `seed_from_u64(42)` makes backtracking deterministic.

**Perturbation:** read the issue reporter's exact words and trace the sampling path on the llama.cpp backend.

**Evidence collected:**

1. Reporter explicitly says: *"Distinct runs seem to give the same sequence of outputs from the `gen_text()`. So maybe this doesn't have to do with a random value sneaking in per run."*
   → The non-determinism is **within a run**, not across runs. Our PR description inverts this.

2. Maintainer `mmoskal` (2024-04-15): *"It looks like it's only a problem with the llama.cpp backend (when using orca deployment it seems deterministic)."*
   → `LogitsProcessor::new` is in `rllm/rllm-base/src/logits.rs` and is called by **both** rllm-cuda (`tmodel.rs:172`) and rllm-llamacpp (`tmodel.rs:148`). If `from_entropy()` were the cause, the orca/CUDA backend would be non-deterministic too. It isn't. So `from_entropy()` cannot be the cause.

3. `LogitsProcessor::new(&req.sampling_params)` is called once per request (`engine.rs:287`). After construction the RNG state advances with each `distr.sample(&mut state.rng)` call. On backtrack, `Sequence::splice_tokens` truncates `self.tokens` (`seq.rs:149-156`), but **does not rewind `SequenceGroup.logits_processor.rng`**. So even with `seed_from_u64(42)`, sampling at logical position L on first visit (RNG state R₀) vs after backtrack (RNG state R_many) uses different RNG state → different tokens.

4. `SamplingParams::default().temperature = 0.0` (`config.rs:134`). At T=0, both backends take `sample_argmax` (`llamacpp/tmodel.rs:150`, no RNG consumed). The reporter's script doesn't set temperature; if it ran at the default, RNG isn't even on the critical path.

**Trajectory:** divergent against. Three independent lines of evidence (cross-backend symmetry, RNG non-rewind, T=0 default) all say `from_entropy()` is not the cause.

**Status:** ❌ **killed**

**Edge generated:** if the bug is within-run on llama.cpp only, the cause is either (a) llama.cpp numerical non-determinism (batch reduction order, KV-cache mutation across backtrack), or (b) some other state in the llamacpp `TModel` path that isn't reset on splice. Investigate before re-shaping the fix.

---

## H₁ — "The CI failure is unrelated to our change"

**Perturbation:** read failing CI log.

**Evidence:** `error: toolchain 'stable-x86_64-unknown-linux-gnu' does not support target 'wasm32-wasi'; did you mean 'wasm32-wasip1'?` — the rust toolchain renamed `wasm32-wasi` to `wasm32-wasip1`. The workflow file references the old name. Our diff doesn't touch the workflow, the target list, or any wasm code.

**Trajectory:** convergent.

**Status:** ✅ **confirmed** — CI is environmentally broken on `main` too. Master is red, not just this PR. Even a perfect fix would land red until the workflow is updated.

---

## H₂ — "Repo dormancy makes time-to-review long"

**Perturbation:** check last merge, last push.

**Evidence:** `pushedAt` 2025-01-22; previous PR (#118) merged 2024-11-10; PRs from Jul/Oct 2024 still open. No reviewer movement on our PR for 7 days, only the CLA bot acknowledgment.

**Status:** ✅ confirmed. Expected return on landing this PR soon is low regardless of quality.

---

## H₃ — "Test file location is unconventional"

**Perturbation:** `test_backtrack_determinism.py` at repo root vs. other test layouts in the repo.

**Evidence:** existing pyctrl samples live under `controllers/pyctrl/samples/` and `controllers/aici_abi/`. Repo root has no other top-level python test. Also, the test requires a running aici server with a model — it's an integration test, not a unit test, and it can't run in CI.

**Status:** ⚠️ partial. Even if the fix were right, reviewer would push back on placement and on having no CI-runnable test.

---

## Graph state

| Node | Claim | Trajectory | Status |
|------|-------|------------|--------|
| H₀ | `from_entropy()` is the cause | divergent against | ❌ killed |
| H₁ | CI red is environmental | convergent | ✅ confirmed |
| H₂ | Repo dormant | convergent | ✅ confirmed |
| H₃ | Test placement off | partial | ⚠️ |

## Frontier (if continued)

- **H₀.a:** within-run non-determinism on llama.cpp at T>0 — is `SequenceGroup.logits_processor.rng` the source, and would re-seeding at each splice (e.g., `seed_from_u64(hash(prefix_tokens))`) make backtracking idempotent?
- **H₀.b:** at T=0 (greedy), is there still non-determinism? If yes, the cause is in llama.cpp's logit computation (batch order, KV-cache reuse), not in sampling. Needs to be reproduced with the reporter's exact script.
- **H₀.c:** is the maintainer's "orca is deterministic" observation still true on current main, or has rllm-cuda diverged?

## Recommendation

This PR has three problems, the first of which is fatal:

1. **The diagnosis is wrong.** The reporter said cross-run is deterministic; the PR claims `from_entropy()` (which only affects cross-run) is the cause. Both backends share `LogitsProcessor::new`, and only one is broken — `from_entropy()` cannot explain that asymmetry. Even after the seed change, RNG state is not rewound on backtrack, so within-run backtrack idempotency isn't restored.
2. **CI is red on `main`.** Won't merge regardless.
3. **Repo is dormant.** Won't be reviewed soon.

**Suggested action:** close the PR (or convert to draft) and either drop, or reopen H₀ with the right perturbation: reproduce the reporter's script on current llama.cpp backend, instrument the splice path to log RNG state and chosen token across backtracks, and only then propose a fix.

## Reasoning modes

- H₀ kill: deduction from code (RNG not rewound on splice) + induction from reporter's own statement (cross-run deterministic) — confidence ~95%.
- H₁, H₂: induction from CI logs and gh metadata — confidence ~99%.
- Frontier H₀.a/b/c: abductions — confidence 60-70%, would need experiments to classify.

---

## Reinvestigate 2026-05-18 — substrate re-entry on CI red

Substrate routed this PR back through investigate after attest verdict. Re-pulled failing log tails for runs 25636248686 (AICIrt build) and 25636248690 (Markdown link check).

- AICIrt failure point unchanged: `rustup target add wasm32-wasi` → `error: toolchain 'stable-x86_64-unknown-linux-gnu' does not support target 'wasm32-wasi'`. Step fires before any cargo invocation on PR code. Re-confirms **H₁**.
- Workflow blob at head SHA (`.github/workflows/aicirt.yml:19`) still reads `rustup target add wasm32-wasi`. Same on main — repo-wide infra rot, not PR-introduced.
- No new commits on the branch since the prior investigation (last activity is the CLA-bot ack 2026-05-11). H₀ status unchanged: **fix is wrong by the prior diagnosis**.

**No new edges opened.** The CI redness was already classified as environmental, and the diagnosis was already killed. Nothing in the PR's code path can address either. The fix would need to be redesigned (per H₀.a/b/c) before any code-side reinvestigation is informative, and even then CI would be red until the workflow is patched on master.

**Halting with `human-gated`.** Re-entering the worktree to push more commits doesn't change either failure mode. Options for the operator:

1. **Close (or convert to draft) #122** per the prior round's recommendation — the diagnosis is wrong and the repo is dormant.
2. **Leave it** — the CLA is signed, the patch is small; if the maintainer ever returns they can decide.
3. **Open a separate one-line CI PR** patching `wasm32-wasi` → `wasm32-wasip1` in `.github/workflows/aicirt.yml`. Independently useful for the repo (every PR is red on this), but a second concurrent PR in a dormant repo, and not in scope of #122.

No code change recommended on the existing branch.
