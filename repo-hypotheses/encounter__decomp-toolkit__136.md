# encounter/decomp-toolkit#136 — `_rom_copy_info` generated twice

## Issue

Splitting Scooby Doo - Mystery Mayhem (NTSC, .init at 0x80014460) fails with
`Symbol _rom_copy_info (0x800168D0..0x8001696C) overlaps with symbol _rom_copy_info (0x800168E8..0x8001696C, align 1)`.

Two `_rom_copy_info` symbols are emitted at addresses 24 bytes apart. The later one (0x800168E8, size 0x84) and the earlier one (0x800168D0, size 0x9C, with `data:4byte` tag) end at the same byte (0x8001696C — the table's null terminator).

## H₀ — Two independent code paths add `_rom_copy_info`

- **Hypothesis**: the symbol is created by two unrelated passes that don't dedupe by name.
- **Perturbation**: grep for writers of `"_rom_copy_info"`.
- **Trajectory**: divergent confirm.
  - `src/util/dol.rs:564-582` — `process_dol` scans the .init section, finds the table, and adds the symbol with `replace=true`.
  - `assets/signatures/__init_data.yml` — the `__init_data` function signature lists `_rom_copy_info` as a relocation target (PpcAddr16Ha/Lo on the `lis/addi` pair at offset 16/20). `apply_signature` (`src/util/signatures.rs:188`) calls `apply_symbol(...)` → `add_symbol(..., false)` at the relocation's resolved target address.
- **Dedup check**: `Symbols::add` (`src/obj/symbols.rs:244-258`) finds existing symbols by `(section_index, address)` only — never by name. Two symbols with identical names at different addresses both survive.
- **Kill condition**: if the two paths produced the *same* address, dedupe would happen on (section, addr) and there'd be no double symbol. They don't, so dig into why the addresses diverge.

## H₁ — `process_dol`'s scan misses the first 2 entries of `_rom_copy_info`

- **Hypothesis**: the table really starts at 0x800168D0 (where the signature relocation points). The DOL scan finds 0x800168E8 because it's looking for the wrong sentinel.
- **Perturbation**: read `src/util/dol.rs:243-265`.
  ```rust
  loop {
      let value = read_u32(buf, dol.as_ref(), addr)?;
      if value == first_rom_section.address || value == entry_point {
          break Some(addr);
      }
      addr += 4;
  }
  ```
  The scan accepts only two values as the `rom` field of the first entry: the first non-BSS DOL section's address, or the entry point. For most CodeWarrior layouts both are 0x80014460 (`.init`).
- **Predicted divergence**: Mystery Mayhem's `_rom_copy_info` has entries for sections OTHER than `.init` at positions 0 and 1. Their `rom` values are addresses of `.extab`/`.extabindex`/`.text*` — not the entry point or DOL-first section. The scan steps past them in 4-byte increments and only stops at entry 2, where `rom = 0x80014460` matches.
- **Evidence**:
  - 0x800168E8 − 0x800168D0 = 0x18 = 2 × 12-byte entries. The miss is exactly 2 entries.
  - Both ranges end at 0x8001696C (the null terminator). Forward walk is correct; the start anchor is wrong.
  - The signature-driven path independently resolved the true start (0x800168D0) from the `lis/addi` relocation embedded in `__init_data`, which is authoritative because the code itself loads that address.
- **Trajectory**: divergent confirm.
- **Provenance** (Phase 2.5):
  - `git blame src/util/dol.rs` shows the scan logic has been in place since the early DOL-handling code. The `first_rom_section.address || entry_point` heuristic predates the modern multi-text-section layout used by some GC/Wii games (Mystery Mayhem has more than one `.text` section based on the symptom).
  - No prior issue or PR matches "rom_copy_info" — first report of this pattern.

## H₂ — Why the second symbol gets `data:4byte`

- **Hypothesis**: after `process_dol`, the signature pass adds a 0-size object symbol at 0x800168D0. Later, analysis sees a 4-byte word loaded from 0x800168D0 (the `lis/addi` lo16 reload), so the symbol's `data_kind` gets tagged `Int32`/`4byte`.
- **Status**: corollary, not load-bearing. The headline bug is the duplicate; the data_kind tag is just a downstream symptom of the size-unknown symbol being treated as a 4-byte access by `Tracker`.
- **Trajectory**: convergent (explains the cosmetic detail; not pursued further).

## Diagnosis

`process_dol`'s scan-for-anchor logic is too narrow. It assumes the first `_rom_copy_info` entry's `rom` field is either the DOL-first non-BSS section address or the entry point. When the game has multiple text sections and the first 1+ entries describe non-init sections, the scan walks past them and anchors mid-table. Forward walk still terminates correctly at the null entry, so the *end* is right but the *start* is short by N entries.

The signature pass then places `_rom_copy_info` at the true start (from a relocation), and since `Symbols::add` dedupes by `(section, address)` and not by name, both survive.

## Fix shape

In `process_dol` (`src/util/dol.rs`), after the existing forward scan finds an anchor, walk *backward* in 12-byte steps while the preceding entry still looks like a valid `_rom_copy_info` row:

- `rom == copy`
- `size > 0`
- `rom` matches some non-BSS DOL section address (i.e. plausibly the start of a ROM-loaded section)

Stop at the first row that fails any check. Use that as the true start.

This is conservative: the forward scan still establishes the anchor (so existing well-behaved DOLs are unaffected), and the backward extension only fires when preceding 12-byte windows look like real entries. False positives would require three consecutive u32s where the first equals the second, the third is nonzero, and the first matches a section address — extremely unlikely as random instruction encoding.

## Reasoning modes

| Claim | Mode | Confidence |
|---|---|---|
| Two paths add the symbol | Deduction (read code) | 98% |
| `Symbols::add` dedupes only by (section, addr) | Deduction (read code) | 99% |
| Scan anchor misses preceding entries | Abduction from address gap (24 bytes = 2 entries) | 90% |
| Backward-walk fix is conservative | Deduction (forward scan unchanged) | 95% |
| Fix actually resolves user's case | Induction — UNTESTED without the user's DOL | 65% |

## Frontier edges

- Phase 6 (benchmark/test) — we don't have the user's DOL. Best we can do is a unit test that constructs a synthetic DOL where `_rom_copy_info` has entries preceding the `.init` row. Will add.
- Maintainer might prefer a different fix shape (e.g. broaden the anchor test directly rather than backward-walking). Open to redesign at review time.

## Status

- Diagnosis: confirmed.
- Fix: drafted (see PR draft).
- Test: synthetic DOL test to add.
- Phase 8 (ship): pending human gate.
