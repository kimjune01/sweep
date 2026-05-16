# tracel-ai/burn Triage Graph

Repo: https://github.com/tracel-ai/burn
Stars: ~15K | Open PRs: 7 | Language: Rust

## Repo Health

- Maintainers active: yes (laggui, nathanielsimard respond within days)
- CI: cargo test, clippy, rustfmt
- Merge velocity: moderate (PRs reviewed within 1-2 weeks)
- Competition density: low (7 open PRs)

## Good-First-Issues Scanned

### #544 — Training metrics
- **Status**: PICKED (BLEU score)
- **Remaining unchecked items**: BLEU, ROUGE, General GPU util, General GPU memory
- **BLEU**: No competing PR. Last comment from majiayu000 (2026-03-21) proposed BLEU/ROUGE but never opened a PR. Pattern is clear from CER/WER/AUROC.
- **ROUGE**: Uncontested. Next candidate after BLEU lands.
- **GPU util/memory**: Blocked on cross-vendor crate selection (laggui comment 2026-01-12).

### #4312 — Image quality metrics
- **Status**: SKIP. Only A-FINE remains, already claimed by Capataina with PR #4894 open.

### #2406 — Add DataframeDataset example
- **Status**: Available but low-signal. No acceptance criteria beyond "have an example." Docs-only, no code merge signal.

### #2191 — Revamp notebooks
- **Status**: Vague scope. Tyooughtul asked to be assigned (2024), no follow-up. Too open-ended for a first PR.

### #1265 — burn-profiler crate
- **Status**: Large scope. nathanielsimard wants flamegraph integration with CubeCL profiling. Not good-first-issue material despite label.

### #1244 — Source button in docs
- **Status**: Infrastructure issue. Requires changing doc build pipeline (--no-deps removal). Multiple people discussed, no solution landed. Risk of scope creep.

### #282 — cargo-generate template
- **Status**: Old (2022). nathanielsimard unsure about cargo-generate. No clear acceptance criteria.

## Selected: #544 BLEU score

- **Why**: Uncontested, mechanical pattern (copy CER/WER shape), maintainer-listed, clear acceptance criteria.
- **Implementation**: `crates/burn-train/src/metric/bleu.rs` — sentence-level BLEU with configurable max_n, pad token support, modified n-gram precision + brevity penalty.
- **Tests**: 9 tests, all passing. 152 total crate tests pass.
- **Branch**: `feat/bleu-metric`
- **Commit**: 9d8315a3e

## Pipeline Next Steps

1. Push branch, open PR referencing #544
2. After BLEU merges: implement ROUGE (same pattern, different algorithm)
3. After 2-3 merges: graduate to non-good-first-issue work
