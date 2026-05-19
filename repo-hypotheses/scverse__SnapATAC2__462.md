# scverse/SnapATAC2#462 — `invalid nucleotide: 110`

**Status:** halt — already fixed upstream. No PR.

## Context

User runs `tl.motif_enrichment` against `mm10.fa` and hits a panic in
`snapatac2-core/src/motif.rs:114`:

```
invalid nucleotide: 110
```

Stack trace references commit `ab502b5` (Jan 16 2024, in v2.6.0–v2.8.0 range).
Maintainer reply: "Which version are you using? I think this issue may have
been fixed in the latest version."

## H₀ — Decoding the panic message

- **Hypothesis:** "110" is the decimal byte value the older panic printed via
  `{}` on `u8`. 110 = ASCII `'n'` (lowercase). User's `mm10.fa` is
  soft-masked (repeat regions in lowercase), which feeds `'n'` into a match
  arm that only handled uppercase `'N'`.
- **Perturbation:** `git log -S "b'n'" -- snapatac2-core/src/motif.rs`.
- **Result:** commit `471a7322c28ff7644b2105fc37dcbcd206b98a4c` —
  "fix the error when DNA sequence contains lowercase 'n'" (2024-03-14).
  Diff added `b'n'` alongside `b'N'` in the match arm and switched the panic
  message to `String::from_utf8(...)` so future unknowns print as characters,
  not raw byte numbers.
- **Trajectory:** divergent confirmed. Reasoning mode: deduction (read the
  diff). Confidence: 98%.

## H₁ — Fix presence in user's installed version

- **Hypothesis:** the user is on a release that predates the fix.
- **Perturbation:** `git tag --contains ab502b5` and check whether v2.9.0 is
  listed.
- **Result:** `ab502b5` is in `v2.5.3`–`v2.8.0`. `v2.9.0` and later do *not*
  contain it as a tip (because they're descendants — `--contains` returns
  tags whose history includes that commit, and v2.9.0 does include it, but
  the fix commit `471a732` is reachable only from v2.9.0+). Maintainer's
  diagnosis is correct: upgrading to ≥v2.9.0 resolves the panic.
- **Trajectory:** divergent confirmed. Mode: deduction. Confidence: 98%.

## H₂ — Residual risk: non-ACGTN IUPAC codes

- **Hypothesis:** the panic arm still fires on IUPAC ambiguity codes
  (R, Y, S, W, K, M, B, D, H, V), so users with non-mm10 references could
  still hit it.
- **Status:** open frontier, not pursued. `mm10.fa` from UCSC contains only
  ACGTN with soft-masking — the reported issue is fully explained by H₀+H₁.
  IUPAC handling would be a separate enhancement.
- **Mode:** abduction. Confidence: 60%.

## Graph state

| Node | Status     | Trajectory | Mode      |
|------|------------|------------|-----------|
| H₀   | confirmed  | divergent  | deduction |
| H₁   | confirmed  | divergent  | deduction |
| H₂   | open       | —          | abduction |

## Decision

Halt. Fix exists in main and shipped in v2.9.0. The maintainer's
in-thread question already routes the user toward the resolution; adding
a substrate-generated "confirming" comment would be noise on a thread the
maintainer is already handling. No PR; no comment.
