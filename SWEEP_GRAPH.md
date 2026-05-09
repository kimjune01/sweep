# Sweep Graph (2026-05-09, tick 6)

**Repos:** 70+ total. 36 triaged, ~39 ready, 1 monitoring, 11 evicted.
**Open PRs:** 21 (19 awaiting review, 2 changes requested)
**Merged:** 1 (bat #3734)
**Closed without merge:** 3 (pallets bulk-close)
**Agents running:** 4 (1 revision, 2 triage, 1 push)

## Unified Punch List

### MERGED

| Repo | # | Title | Merged by | Turnaround |
|------|---|-------|-----------|------------|
| **sharkdp/bat** | **3734** | zsh completion force-plain | keith-hall (COLLABORATOR) | 12min |

### CHANGES REQUESTED (revision in progress)

| Repo | # | Reviewer | Feedback | Agent |
|------|---|----------|----------|-------|
| litestar | 4755 | provinzkraut | opt key not static | revising |
| ~~numpyro~~ | ~~2188~~ | ~~Qazalbash~~ | ~~frac, equation, jax.scipy~~ | **DONE — pushed** |

### AWAITING REVIEW (19 PRs)

| Repo | # | Title | Age |
|------|---|-------|-----|
| gemini-cli | 24736 | union-find context compaction | 33d |
| compiler | 1162 | strip dead imports client:only | 2d |
| ruff | 25066 | TD003 Jira-style issue IDs | <1d |
| mypy | 21449 | dotted names error message | <1d |
| mcp-cli | 242 | SSE ping health check | <1d |
| mvdan/sh | 1332 | BinaryNextLine test/arith | <1d |
| VictoriaMetrics | 10934 | basicAuth.usernameFile | <1d |
| burn | 4937 | BLEU score metric | <1d |
| OTel collector | 15281 | consumer testable examples | <1d |
| gh-dash | 868 | confirmation default No | <1d |
| node_exporter | 3652 | thermal_zone error handling | <1d |
| harbor | 23223 | SBOM permission fix | <1d |
| pyro | 3451 | negative plate sizes | <1d |
| streamlit | 15105 | theme color map marker | <1d |
| blackjax | 907 | nested Rhat diagnostic | <1d |
| polars | 27561 | qcut empty include_breaks | <1d |
| pylint | 11002 | kwargs no-value-for-parameter | <1d |
| thanos | 8816 | bucketweb labels display | <1d |
| numpyro | 2188 | distribution math docs | <1d |

### HELD

| Repo | # | Reason |
|------|---|--------|
| prometheus/client_golang | 483 | issue stale-closed by bot |

### CLOSED WITHOUT MERGE

| Repo | # | Reason |
|------|---|--------|
| pallets/click | 3414 | davidism bulk-close |
| pallets/jinja | 2166 | davidism bulk-close |
| pallets/quart | 464 | davidism bulk-close |

### COOLDOWN (tinygrad, until May 22)

| # | Title | Viability |
|---|-------|-----------|
| 12296 | max backward underflow (float16) | STRONG |
| 6909 | bf16 autocast ClangRenderer | OK |

### BLOCKED

| Repo | # | Blocker |
|------|---|---------|
| gemini-cli | 25693/25689 | competing PRs |
| nodejs/node | 62838 | competing PR #63162 |
| TypeScript | 30408 | 0/7 prior attempts |

### IN TRIAGE (agents running)

| Repo | Hypothesis | Status |
|------|-----------|--------|
| IBM/mcp-context-forge | H2 warm lead | triage running |
| oxc-project/oxc | H1/H6 lint-rule-port | triage running |
| ~~gemini-cli-action~~ | ~~H2 warm lead~~ | **ARCHIVED — evicted** |

### UNPUSHED

| Repo | Branch | Agent |
|------|--------|-------|
| astral-sh/ty (ruff) | fix/hover-content-format | push agent running |

## Cross-repo Findings

### Pallets org rejection (NEW)
davidism closed click #3414, jinja #2166, quart #464 within 21 seconds. No reviews, no comments, all CI green. **Org-wide rejection.** All three evicted.

### bat merge validates solo-maintainer+collaborator pattern (NEW)
bat #3734 merged in 12min by keith-hall (COLLABORATOR), not the solo maintainer sharkdp. Repos with active collaborators merge faster than expected. Watch: gh-dash, mvdan/sh (same pattern).

### Archived repo trap (NEW)
gemini-cli-action was archived 2025-08-05, superseded by google-github-actions/run-gemini-cli. Warm-lead by org proximity does not imply actionable repo. Archive status trumps all signals.

### PPL/Bayesian cluster
numpyro #2188 (revision done), pyro #3451, blackjax #907 — three PRs in probabilistic programming. Same JAX/PyTorch ecosystem.

### CNCF/observability cluster
prometheus node_exporter #3652, thanos #8816, OTel collector #15281, VictoriaMetrics #10934 — four PRs, same Go patterns, CNCF governance.

### Astral/linting cluster
ruff #25066 (TD003), ty branch (hover content format) — same repo/org. AI disclosure required per #24198.

### IBM org cluster
mcp-cli #242 (pushed), mcp-context-forge (in triage). 3 prior merges establish standing.

### bf16 cluster (tinygrad-internal)
#6909 <> #11756 <> #16114. Same dtype, different failure modes.

### AI policy spectrum
- **Welcoming:** open-webui, numpyro (90% merge)
- **Neutral:** prometheus (CNCF), excalidraw, mvdan/sh, bat (merged!)
- **Screening:** ruff (AI disclosure), TypeScript
- **Hostile:** pallets (bulk-close), attrs, telegraf (CLA ban)

## Eviction Log

| Repo | Date | Reason |
|------|------|--------|
| withastro/astro | May 9 | dormant |
| python/cpython | May 8 | monitoring only |
| faster-cpython/ideas | May 8 | monitoring only |
| SoarGroup/Soar | May 8 | 0% merge rate |
| Aider-AI/aider | May 9 | 10-50x merge ceiling |
| python-attrs/attrs | May 9 | hostile AI policy |
| influxdata/telegraf | May 9 | CLA ban on AI code |
| **pallets/click** | **May 9** | **bulk-close by davidism** |
| **pallets/jinja** | **May 9** | **bulk-close by davidism** |
| **pallets/quart** | **May 9** | **bulk-close by davidism** |
| **gemini-cli-action** | **May 9** | **repo archived 2025-08** |

---

*Tick 6. 1 merge (bat). 4 evictions (pallets x3, gemini-cli-action). Numpyro revision pushed. 4 agents still running. 21 open PRs across 21 repos.*
