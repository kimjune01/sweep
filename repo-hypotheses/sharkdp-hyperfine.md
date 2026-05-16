# Triage Graph: sharkdp/hyperfine

## Issue #781: HYPERFINE_ITERATION not visible in prepare/conclude commands

**Status**: IMPLEMENTED
**Branch**: fix-hyperfine-iteration-env-var
**Commit**: 9cb42faab1466ba07aba64ac4c08417451da4b5c

### Problem
The `HYPERFINE_ITERATION` environment variable was only visible in the main benchmark command, not in `--prepare` and `--conclude` commands.

### Root Cause
- `run_intermediate_command` hardcoded `BenchmarkIteration::NonBenchmarkRun`
- `NonBenchmarkRun.to_env_var_value()` returns `None`, so the env var was not set
- Both `run_preparation_command` and `run_conclusion_command` called `run_intermediate_command`

### Solution
1. Added `iteration: BenchmarkIteration` parameter to:
   - `run_intermediate_command`
   - `run_preparation_command`
   - `run_conclusion_command`

2. Updated all call sites:
   - Warmup: `BenchmarkIteration::Warmup(i)`
   - Initial measurement: `BenchmarkIteration::Benchmark(0)`
   - Subsequent runs: `BenchmarkIteration::Benchmark(i + 1)`

3. Kept setup/cleanup using `NonBenchmarkRun` (correct - they run once per benchmark)

### Reviews
- **Codex**: Approved implementation
- **Gemini 3.1 Pro**: "No logic errors, missed edge cases, or inverted conditions were found. The changes flawlessly meet the goal."

### Test Results
```
$ hyperfine --runs 3 --prepare 'echo "prepare ${HYPERFINE_ITERATION}"' 'echo "main ${HYPERFINE_ITERATION}"' --conclude 'echo "conclude ${HYPERFINE_ITERATION}"' --show-output

prepare 0
main 0
conclude 0
prepare 1
main 1
conclude 1
prepare 2
main 2
conclude 2
```

All 58 tests pass (19 unit tests + 39 integration tests).

### Competing PRs
- #857 (7 weeks old, no reviews)
- #807 (13 months old, no reviews, community engagement)
- #859 (closed)

### Maintainer Context
- Issue acknowledged by @sharkdp: "this should be easy to fix, I think"
- In milestone: hyperfine 2.0
- Good first issue label
