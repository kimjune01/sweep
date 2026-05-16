# pingcap/tiflow#12637 — Vulnerable dependencies

**Status:** Halted at policy gate (maintainer self-PR).

## H₀ — Issue worth investigating?

- **Observation:** Issue reports 5 vulnerabilities flagged by `govulncheck`: golang.org/x/net@v0.50.0 (×2), grpc@v1.77.0, otel/sdk@v1.38.0, pingcap/tidb (nil deref).
- **Perturbation:** `gh pr list --search` for existing dep-bump PRs in the same repo.
- **Result:** PR #12638 "Upgrade vulnerable dependencies" opened by the same author (`dveeden`) **26 seconds after** the issue (2026-05-15T08:19:35Z vs 08:19:09Z).
- **Classification:** Divergent against. Reporter == fixer; no maintainer attention is available.
- **Edge:** Halt. Per `[[feedback-maintainer-self-pr]]`.

## Decision

Drop. Not a slop-offer candidate, not an investigation candidate.
