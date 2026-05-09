# RETRO_GRAPH: SoarGroup/Soar

## Own Outcomes (kimjune01)

| PR | Title | State | +/- | Verdict |
|----|-------|-------|-----|---------|
| #581 | soar-eval: per-module eval harness | OPEN | +1039/-0 | Large feature, no response yet |
| #580 | smem: --sweep-dominated (destructive compaction) | CLOSED | +1294/-2 | Rejected — experimental, changes retrieval |
| #579 | smem: --redundancy-check (read-only) | CLOSED | +858/-2 | Rejected — large addition |
| #578 | epmem: kernel-mediated copy to smem | CLOSED | +413/-2 | Rejected — experimental cross-module |
| #577 | rl: EMA-based low-update trigger | OPEN | +250/-1 | No response yet |

**Pattern: 3/5 closed, 2/5 open with no response.** All PRs are large experimental features (+250 to +1294). Zero merges. The maintainer (scijones) has not engaged with any of them.

## Prior Art (last 10 merged PRs)

scijones: **8/10** — overwhelmingly self-merged. External merges:
- moschmdt (#572): +1314/-70 — SWIG bindings, large but accepted
- ShadowJonathan (#555): +3/-14 — tiny build fix

External merge rate: **2/10** (20%). moschmdt's merge shows large PRs can land, but it was SWIG bindings (tooling), not core cognitive architecture changes.

## Meta-hypotheses

| ID | Hypothesis | Evidence | Classification |
|----|-----------|----------|----------------|
| H0 | Maintainer merges external PRs | 2/10 — barely | Weak — near-solo project |
| H1 | Tooling/build PRs merge; core changes don't | moschmdt (tooling) merged, all kimjune01 (core) closed | **Confirmed** |
| H2 | Large experimental PRs get rejected | 3 closed, all 400+ lines | **Confirmed** |
| H3 | No-response = soft rejection | #577, #581 open with zero comments | Likely — scijones merges own work actively |
| H4 | Read-only/diagnostic PRs have better odds | #579 (read-only) still closed | **Falsified** — even conservative PRs rejected |

## Base rates

- External merge rate: 20% (low, tooling-biased)
- Core architecture PR merge rate: 0% (n=5, all rejected or ignored)
- Maintainer engagement with external core PRs: zero comments observed

## Risk

Very high. This is effectively a solo-maintainer project for core changes. The maintainer merges his own work and occasional tooling contributions. Five PRs with zero engagement suggests the contribution model is not open for cognitive architecture changes. Consider: (1) opening an issue first to gauge interest before coding, (2) targeting build/tooling gaps instead, or (3) treating this as a fork-worthy upstream.
