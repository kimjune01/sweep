# Triage Graph: mvdan/sh (kimjune01)

**Scan date:** 2026-05-09
**Mode:** dry-run

## Scan Table

| # | Title | State | Score | Effort | Signal | Status |
|---|-------|-------|-------|--------|--------|--------|
| 813 | BinaryNextLine missing for test/arith expressions | OPEN | 5.72 | Medium (~35 lines) | Maintainer help-wanted | INVESTIGATED |
| 1233 | zsh associative array key mangling | OPEN | 5.72 | — | Design limitation | SKIP |

## T813: BinaryNextLine (-bn) missing for BinaryTest and BinaryArithm

### Root Cause

`printer.go:1236` checks `p.binNextLine` only inside `case *BinaryCmd` (line 1223). `testExprSameLine` (line 937) handles `BinaryTest` by always writing op then calling `p.testExpr(expr.Y)` for AndTest/OrTest — never checks `binNextLine`. Similarly, `arithmExprRecurse` (line 880) for `BinaryArithm` writes `op + space + Y` with no next-line logic.

### Fix (~35-45 lines)

In `testExprSameLine`: when `binNextLine` is true and `expr.Y` is on a later line, emit `\` + newline before the operator (mirroring BinaryCmd logic). Same pattern for `arithmExprRecurse`. ~20-30 lines printer + ~15 lines test cases.

### Test Approach

Add input/output pairs to `TestPrintBinaryNextLine` table in `printer_test.go` (line 795).

### PR Viability: STRONG

mvdan actively merges external PRs — 8 from 5 contributors in last 3 months. High code quality bar but welcoming. Maintainer said "I think it would probably make sense to change the feature."

## T1233: zsh associative array hyphens — SKIP

Design limitation. `eitherIndex()` parses bracket contents as arithmetic; `-` in keys becomes `Sub` operator. No clean fix without type tracking. mvdan acknowledges as caveat, not bug.

---

*Dry run — no remote side effects.*
