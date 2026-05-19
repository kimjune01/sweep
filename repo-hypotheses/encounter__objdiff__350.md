# Hypothesis graph: encounter/objdiff#350

> MSVC Xbox 360 jump-table `lis`/`addi` relocations are wrong — objdiff is dropping the addend from the IMAGE_REL_PPC_PAIR record.

## H₀ — Baseline observation

- **Claim:** for MSVC PPC (Xbox 360) jump-table accesses, the relocation that should point to the first instruction *after* `bctr` instead points to instruction 0 of the function.
- **Reporter evidence:** `.obj` / `.s` show the correct reloc + addend; objdiff renders it as 0-addend.
- **Reporter pointer:** `objdiff-core/src/arch/ppc/mod.rs:241` — the closure that handles the matched IMAGE_REL_PPC_PAIR for a REFHI/REFLO always returns `addend: 0`. Reporter tried `reloc.addend()`, no luck.
- **Mode:** induction (reporter's own measurement). Confidence 95%.
- **Status:** confirmed.

## H₁ — `reloc.addend()` is always 0 for PE/PPC because the object crate doesn't lower the PPC kinds

- **Perturbation:** read `object` 0.39.1's `coff/relocation.rs` and look at the per-machine match.
- **Result:** the match has arms for ARM, ARM64, I386, AMD64. **No arm for PPC.** Anything PPC falls to `unknown = (K::Unknown, E::Unknown, 0, 0)`, so the cooked `addend` is hardcoded `0` regardless of what's on disk. `target = Symbol(relocation.symbol())` — i.e. the raw `symbol_table_index` field is exposed as a SymbolIndex.
- **Trajectory:** divergent — single sample fully explains reporter's "`reloc.addend()` didn't work."
- **Mode:** deduction. Confidence 99%.
- **Status:** confirmed. Kill condition for reporter's attempted fix.
- **Edge:** the actual addend has to come from the raw record, not from `Relocation::addend()`.

## H₂ — For COFF/PPC, the PAIR record's `SymbolTableIndex` field encodes the addend (signed 32-bit displacement), not a symbol index

- **Premise:** MSVC PE/PPC COFF spec. IMAGE_REL_PPC_PAIR is unique: when it follows a REFHI/REFLO, its `SymbolTableIndex` field holds the displacement (addend) to be combined with the previous relocation's hi/lo halves, *not* an index into the symbol table.
- **Corroboration from objdiff's own code:**
  - The cooked Relocation for the PAIR exposes `target() = Symbol(SymbolIndex(symbol_table_index as usize))`.
  - Line 240 matches `Symbol(_)` — i.e. it *receives* the field but throws it away. The discarded number is exactly the addend.
- **Perturbation predicted:** pull `idx.0` out of `RelocationTarget::Symbol(idx)`, reinterpret as `i32` (to preserve sign), feed as the override's addend. The 32-bit `i32 -> i64` cast preserves negatives.
- **Trajectory predicted:** divergent — addend matches what `.s`/`.obj` show, jump-table targets land on the correct instruction.
- **Mode:** abduction supported by deduction (object crate raw layout matches MS COFF spec). Confidence 80% pending live verification on a real MSVC X360 `.obj`.
- **Status:** open — needs prework binary to confirm on actual artifact.

## H₃ — Provenance: line 241 is a stub, not a deliberate "drop addend" choice

- **Perturbation:** `git log -L 241,247:objdiff-core/src/arch/ppc/mod.rs` on the worktree.
- **Expectation:** the PAIR-found arm was written at the same time as the rest of the COFF PPC support; the `addend: 0` looks like a TODO-shaped placeholder rather than an informed choice. (Pattern fits H₁: when the object crate gives you 0, dropping the value through is path-of-least-resistance.)
- **Mode:** induction (git history). Confidence 90% on "not deliberate."
- **Status:** assumed; not load-bearing for the fix.

## Diagnosis (current best)

The COFF/PPC PAIR matching arm at `objdiff-core/src/arch/ppc/mod.rs:240-247` receives the PAIR record's `symbol_table_index` field — which for PPC PAIR holds the displacement (addend), not a symbol index — and discards it by writing `addend: 0`. The reporter's attempted fix (`reloc.addend()`) fails because the `object` crate does not lower PPC relocation kinds and so reports a cooked addend of 0 unconditionally.

## Proposed fix shape

```rust
|(_, reloc)| match reloc.target() {
    object::RelocationTarget::Symbol(idx) => {
        // For COFF PPC, IMAGE_REL_PPC_PAIR's SymbolTableIndex field
        // encodes the addend (signed 32-bit displacement), not a
        // symbol-table index. The `object` crate doesn't lower PPC
        // relocations, so the cooked `reloc.addend()` is always 0;
        // we read the raw field back out of the Symbol target.
        let addend = i64::from(idx.0 as u32 as i32);
        Ok(Some(RelocationOverride {
            target: RelocationOverrideTarget::Keep,
            addend,
        }))
    }
    target => Err(anyhow!("Unsupported IMAGE_REL_PPC_PAIR target {target:?}")),
},
```

Same edit for the "PAIR not found" map_or default? No — when no PAIR is present, there is no addend to recover; the existing `addend: 0` is correct.

## Frontier edges

1. **Verify on a real MSVC X360 `.obj`** — needs a fixture. The reporter has one (jeff repo). Without it, this is an abduction matching the spec, not an induction.
2. **Sign handling** — jump-table displacements are non-negative in practice, but signed reinterpretation costs nothing and matches the MS spec's wording ("signed 32-bit displacement").
3. **Other PAIR-bearing reloc pairs (SECREL/TOCREL)** — IMAGE_REL_PPC_SECRELHI/LO and TOCREL16 also pair. Same arm currently treats them via `Coff { .. }` default (line 252-255). Out of scope for this issue; flag as a follow-up.

## Reasoning modes

| Node | Mode | Confidence |
|------|------|-----------|
| H₀ | induction (reporter) | 95% |
| H₁ | deduction (object crate source) | 99% |
| H₂ | abduction + deduction (MS spec) | 80% |
| H₃ | induction (assumed) | 90% |

## Pruning log

- Reporter's hypothesis "use `reloc.addend()`" — **killed by H₁**. The object crate does not lower PPC relocs; `addend` is hardcoded 0. Pull the value out of `target` instead.
