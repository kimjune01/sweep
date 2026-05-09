# RETRO_GRAPH: withastro/astro

## Own Outcomes

**#16634 — strip client:only imports from prerender Rollup graph** | CLOSED (self)
Self-closed after <30 minutes. Reason: "Closing in favor of a compiler-level fix. The Vite plugin approach had edge cases (mixed imports, side effects) that are better handled at the source."

Classification against H0-H6: N/A (voluntary withdrawal, not a rejection).

**Strategic read:** This was the correct call. The PR moved the fix upstream to compiler (#1162), where import stripping belongs. The astro-level Vite plugin approach was a workaround. No maintainer engaged, so no reputation cost.

## Cross-Repo Insight

The self-close created the compiler PR (#1162). This is a positive signal: it shows the contributor understands the codebase architecture well enough to pick the right layer. If a maintainer notices the astro PR's close comment pointing to compiler, it may accelerate review of #1162.

## Eviction Note

This repo is evicted from active sweep. No open PRs, no pending issues targeted. Re-enter only if compiler #1162 is rejected and the fix needs to move back downstream.

## Meta-Hypotheses (repo-specific)

- **H0-H6:** Insufficient data from own outcomes (1 PR, self-closed). Rely on compiler and prettier-plugin for hypothesis testing.
- **Cross-repo H5 (bandwidth):** astro is the highest-traffic repo. Maintainer attention is scarcer here than in compiler or prettier-plugin. The decision to fix upstream was bandwidth-aware.
