# etemesi254/zune-image#362 — zune-jpeg `idct_int_1x1` slice-OOB panic

## H₀ — Defensive bounds-check missing in `idct_int_1x1`

**Hypothesis.** `idct/scalar.rs::idct_int_1x1` walks the output buffer by `stride` without bounds checks, so a corrupt JPEG that produces `idct_position` such that `channel[idct_position..].len() < 7*stride + 8` panics at line 36 (`out_vector = &mut out_vector[stride..]`). Sister functions `idct_int` (line 162) and `idct4x4` (line 276) already use the defensive `get_mut(..).unwrap_or(&mut tmp)` pattern.

**Perturbation.** Unit-call `idct_int_1x1(&mut [DC=1024;..], &mut vec![0; 144], stride=208)` — mirrors the reported buffer/stride pair.

**Trajectory.** Divergent — exact error message reproduces: `range start index 208 out of range for slice of length 144` at `scalar.rs:36:37`. Confirms hypothesis.

**Provenance.**

- `3330a8eb jpeg: Temporary measures on some jpeg decoding errors.` (2026-03-11) — added `get_mut(..).unwrap_or(&mut tmp)` to `idct_int` and `idct4x4`, and to `idct_int_1x1` as `if let Some(e) = out_vector.get_mut(stride..stride+8) { e.fill(coeff) }`.
- `58cb7df8 jpeg: Fix wrong idct for scalar 1x1` (2026-03-11, same day) — reverted the 1x1 guard because the previous form wrote to the same offset every iteration (didn't advance `out_vector`), producing a wrong IDCT. The revert restored correctness but reintroduced the original panic.

The bug is a regression caused by fixing a correctness bug in the prior fix. The correct shape combines both: advance the slice **and** bounds-check.

## Fix

```rust
pub fn idct_int_1x1(in_vector: &mut [i32; 64], mut out_vector: &mut [i16], stride: usize) {
    let coeff = ((wa(wa(in_vector[0], 4), 1024) >> 3).clamp(0, 255)) as i16;
    if let Some(row) = out_vector.get_mut(..8) { row.fill(coeff); } else { return; }
    for _ in 0..7 {
        let Some(rest) = out_vector.get_mut(stride..) else { return; };
        out_vector = rest;
        let Some(row) = out_vector.get_mut(..8) else { return; };
        row.fill(coeff);
    }
}
```

Matches the codebase's existing tolerance posture: bad inputs are silently truncated, not propagated as errors, mirroring `idct_int` / `idct4x4`.

## Test

`crates/zune-jpeg/src/idct/scalar.rs` gains two unit tests:

1. `idct_int_1x1_stride_exceeds_buffer_issue_362` — `len=144, stride=208`, exact reported shape.
2. `idct_int_1x1_buffer_smaller_than_one_row_issue_362` — `len=4, stride=8`, even the first row doesn't fit.

Both panic on master with the original error text; both pass with the fix.

The reporter's fuzz sample (`1c5388...txt`) on current dev returns `Err` before reaching the IDCT (other defensive measures in the decode pipeline kick in first), so an integration-level fixture would not be fail-on-master. Unit tests on the function under question are the right scope.

## Graph state

| Node | Status | Shape |
|------|--------|-------|
| H₀ — missing bounds guard | confirmed | divergent |

Frontier: closed.

## Reasoning mode

- Deduction (read code, git blame, identified regression source): 95%
- Induction (unit-tested function, observed exact reported panic): 95%
