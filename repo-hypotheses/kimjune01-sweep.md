# Hypothesis Graph: kimjune01/sweep (the pipe itself)

Meta-investigation of sweep treating itself as the engineered system. Each hypothesis is a load-bearing design choice from the 2026-05-15 → 2026-05-16 session that ought to be falsifiable.

This is distinct from the project's main `HYPOTHESIS_GRAPH.md` (H0-H19), which is about contributor-pipeline patterns across many repos. This file is about sweep-as-architecture.

---

## P1: Per-issue triage beats per-repo triage in a streaming pipeline

**Prediction:** A `/triage <repo>#<issue>` skill (lean, ≤30s, single decision, no fan-out) processes streamed candidates faster and with less variance than `/triage <repo>` (per-repo batch, parallel /investigate fan-out).

**Observation:** 2026-05-15 session — per-repo `/triage` running through SkillActor took ~1.4h per call (re-scanning the whole repo every time). After rewriting to per-issue, target is seconds per call.

**Falsifier:** If per-issue triage averages > 2 minutes per call over n≥30 invocations, the per-repo dedup advantage we lost was load-bearing and the new shape is wrong.

**Status:** Implemented. Needs volume to measure.

---

## P2: Seen-set must NOT mark on filter-dependent rejections

**Prediction:** When the operator turns a knob (lower min_complexity, widen recency window, edit kill list), previously-rejected candidates should re-enter the pool. Marking seen on LLM-rejection permanently excludes issues that might pass under a different filter setting.

**Observation:** Session bug — overnight, every prospect tick reported `considered: 15, filtered: {seen: 15}`. Knob changes had no effect because the seen-set absorbed every prior candidate.

**Falsifier:** If knob-turning still produces no candidate flow after wipe + re-eval policy, the bottleneck is elsewhere (probably search itself is empty).

**Status:** Fixed — only deposit + has_related_pr mark seen.

---

## P3: Warm orgs should ignore label filters; cold orgs need them

**Prediction:** For warm orgs (established standing), the `bug,help-wanted` label gate excludes most issues we could plausibly engage with. Dropping it for the warm-org search path produces more relevant candidates than dropping it globally would.

**Observation:** Global recency search with labels: 8 candidates. Warm-org search WITH labels: ~1 additional. Warm-org search WITHOUT labels: 995. The label was a global firehose hack that doesn't pay for itself on warmth.

**Falsifier:** If LLM-judge reject rate on warm-org candidates is 99%+, the label filter was actually load-bearing for quality and we should reinstate.

**Status:** Implemented. Watch LLM-judge rates per source (global vs warm).

---

## P4: 3 consecutive losses = repo eviction is the right threshold

**Prediction:** Three consecutive closed-unmerged or hanging (>30d open) PRs in one repo is enough evidence that the repo isn't engageable. Anything less risks evicting too aggressively; anything more wastes tokens before the eviction fires.

**Operationalization:** `auto_evict_stale_repos` walks outcomes, counts last-3 per repo, evicts on full-loss streak. Logs `repo_evicted` event.

**Falsifier:** If a repo we evicted *would have* merged the 4th PR with high probability (visible post-hoc by checking other contributors' acceptance there), 3 is too low. If repos consistently merge after 3 closes (e.g., maintainer changed mind), 3 is too low.

**Status:** Implemented. 5 evictions on first sweep (dapr/dapr, jellyfin-tui, speedygrad, gemini-cli-claude, Soar). 2 of those are operator's own repos — accurate signal.

---

## P5: AIMD on `min_complexity` keeps the pipe flowing without violating operator preference

**Prediction:** Auto-loosen on empty streak (multiplicative decrease) keeps work flowing; auto-reset to operator target on utilization recovery (snap back) ensures we don't drift permanently below preference. Operator only tightens manually; pipeline never auto-tightens.

**Falsifier:** If acceptance rate consistently falls when auto-loosened, the loosening is admitting work the substrate can't handle — should add a minimum-tier floor below which we don't loosen even if empty.

**Status:** Implemented. Untested at steady-state.

---

## P6: Cheap deterministic rejections save ~50-70% of LLM judge calls

**Prediction:** `non_bug_title`, `thin_body`, `saturated_thread`, `no_leverage_signals` patterns reject the bulk of garbage candidates before any LLM token. With them, per-fire LLM call count drops materially.

**Observation:** Single test fire: 647 considered → 210 rejected by cheap filters → 226 LLM-rejected as unknown complexity → 78 over-cap → 10 deposited. Cheap layer caught ~32% of total filtering; LLM layer caught ~35%. Without cheap layer, LLM would have judged 437 instead of 226 — roughly 2× the API spend.

**Falsifier:** If patterns become outdated and produce false-positives (rejecting legitimate bug titles that happen to contain "feature"), update or remove. Currently regex is `^(rfc|proposal|feature|...)` anchored — rare false-positive risk.

**Status:** Implemented. Working as designed.

---

## P7: Demand-pull eliminates the need for takt timing

**Prediction:** A puller that fires only when downstream has capacity beats a ticker that fires on a fixed cadence. No tuning of cadence to throughput; the system self-paces.

**Observation:** Replaced ProspectTicker (fixed 60min cadence, then 3min) with ProspectPuller (wait_condition on triage < cap, 15s minimum spacing). The system now never overflows triage and never starves it; cadence-as-knob disappeared.

**Falsifier:** If the puller's wait_condition gets stuck (as happened overnight on fires_total:1), the demand signal isn't propagating reliably enough. Need investigation into Temporal workflow recovery.

**Status:** Implemented. One observed stuck-state overnight — root cause unclear, possibly a transient worker disconnect Temporal didn't recover from.

---

## P8: Anthropic prompt cache makes per-issue LLM judges cheap at scale

**Prediction:** Marking `cache_system=True` on the `should_triage_issue` call brings steady-state input cost to ~10% of full-rate, so the LLM filter becomes affordable at puller cadence (~hundreds of calls/day).

**Operationalization:** Total API spend forecast: $1-3/day with prompt cache active vs $10-30/day without.

**Falsifier:** If puller idles > 5min between fires consistently (cache TTL expires), cache hit rate drops sharply and the cost projection inflates. Or if the system prompt mutates (e.g., min_complexity changes), each change invalidates cache for one call.

**Status:** Implemented. Cost not yet measured against bill.

---

## P9: The HG corpus is the IR of machine reasoning

**Theory (not hypothesis — no falsifier).** Per-investigation HG files at `repo-hypotheses/<owner>__<repo>__<issue>.md` are the intermediate representation between issue (source) and PR (lowered output). The directory's existence as a public archive enables third-party tooling that doesn't exist yet (pattern mining, depth prediction, hypothesis dedup). Cf. "Internal Reasoning of Prose Compiler" (2026-05-15).

---

## P10: Maintainer attention is the headliner waste; everything else is downstream

**Theory.** Closed-unmerged PRs are the most expensive defect because they consume non-renewable maintainer attention. Internal qa pass rates, cache hit rates, drowning depth — all downstream of acceptance. The `sweep waste` report's headliner is acceptance rate; other metrics serve it.

**Corollary (P10a, testable):** Optimizing for internal pass rate while ignoring acceptance produces over-cautious qa (high pass, low ship) OR rubber-stamp qa (high pass, low merge). Either is visible as the gap between qa_converged:pass count and merged count.

**Falsifier for P10a:** If qa pass rate and merge rate move together within ±5%, the qa volley is well-calibrated and the headliner-vs-internal distinction isn't load-bearing.

---

## Frontier (open, no perturbation yet)

- **F1:** Does per-repo retro_param (e.g., `claim_after_investigate: true`) measurably lift acceptance rate when enabled?
- **F2:** Does the 1-week TTL on warm-org PRs actually unblock useful work, or do those slots get immediately re-blocked by new PRs in the same repo?
- **F3:** What's the actual a-priori-vs-post-hoc gap on the depth gauge? (LLM rates an issue MEDIUM; post-PR LoC delta says DEEP, etc.) Needs the calibration loop wired.
- **F4:** Is the InvestigateActor parallelism cap (currently WIP=1 via SkillActor) the right shape, or should /investigate also run concurrent?

---

*Written 2026-05-16 during the post-overnight retro. The pipe just finished its first end-to-end cycle of the new per-issue architecture; numbers above are pre-volume.*
