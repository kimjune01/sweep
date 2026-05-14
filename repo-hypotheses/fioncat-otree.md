# fioncat/otree — hypothesis graph

PR: https://github.com/fioncat/otree/pull/134
Branch: `fix-oom-large-files`
Status: shipped 2026-05-12

## H2_quality — file size check after read causes OOM

**Claim.** `otree` reads the entire file into memory before checking it against `max_data_size`, so a >`max_data_size` file OOMs the process before the size guard can fire.

**Perturbation.** Construct a 35 MiB file and run `otree --to yaml`. Expected: instant size error with no allocation spike. Observed (pre-fix): allocation spike + OOM on memory-tight hosts.

**Fix.** Move the `metadata().len()` check ahead of `fs::read()`. Compare as `u64` (not truncated to `usize`) so the guard is correct on 32-bit targets. Stdin path is handled separately and unaffected.

**Receipts.**

- `cargo test`: 9 unit tests + 1 new integration test (35 MiB file → early rejection) green
- `cargo clippy`: no new warnings
- Manual: `otree --to yaml` on >30 MiB file returns size error instantly, no allocation spike
- Adversarial pass (codex + gemini): no bugs. `live_reload` OOM is pre-existing and out of scope. The metadata-vs-read race is best-effort, same as before. Sparse files handled conservatively. No 32-bit truncation.

**Edges considered and rejected.**

- *Race between metadata check and read.* Acceptable: the guard is best-effort, matches prior contract, and the read path still bounds allocation in the common case.
- *`live_reload` path also OOMs.* Pre-existing, separate code path, out of scope for this PR.
- *Sparse files report logical size.* Conservative bound; rejecting is the safe direction.

## Provenance

Filed by the kimjune01 sweep pipeline as part of the `hg_in_body_2026-05-14` experiment — testing whether linking the hypothesis graph from the PR body changes maintainer review behavior on small Rust repos.
