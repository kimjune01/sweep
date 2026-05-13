# Triage Graph: ggml-org/llama.cpp

Repo: https://github.com/ggml-org/llama.cpp
Stars: 109K | Language: C++ | Merges: daily
AI Policy: Strict. No fully AI-generated PRs. Disclosure required. Human must understand and defend every line.

## Review culture

- Maintainers: ggerganov, slaren, ngxson, others
- Gate: maintainer review required, CI must pass
- Signal: clear code, tests, precise commit messages
- Tiebreaker: ggerganov's design preference (use slot context, use n_past)

## Scanned issues (good first issue, 2026-05-09)

### Bugs (actionable)

| Issue | Title | Status | Competing PRs | Verdict |
|-------|-------|--------|---------------|---------|
| #9933 | n_predict=-2 produces 1 token in server | **PICKED** | #9938 (stale, unaddressed feedback) | Fix ready on `fix/server-n-predict-minus-2`. Codex pass, Gemini pass. |
| #7073 | extern "C" functions throw exceptions | Open | #8210 (stale 10mo, reviewer feedback unaddressed) | Viable next target. clip.cpp moved to tools/mtmd/clip.cpp. Need to check if original issue still reproduces. |
| #10732 | json_schema response_format ignored | Open | #18963, #21537 (crowded) | Skip -- too many competing PRs. |
| #9933 | One token output with n_predict=-2 | See above | See above | See above |

### Bugs (low actionability)

| Issue | Title | Why skip |
|-------|-------|----------|
| #17611 | Wrong default threads in llama-bench | Debated -- community split on physical vs logical cores. Not clearly a bug. |
| #9628 | Failed to run qwen2-57b | Old model, likely OBE |
| #10747 | iOS Swift Xcode build error | 41 comments, complex build system issue, not a quick fix |

### Features (skip per instructions)

#22759, #20632, #17634, #17488, #14909, #13523, #12476, #11031, #10932, #10819, #10688, #10685, #8724, #6855

## Next actions

1. Wait for #9933 PR to be reviewed
2. If merged, investigate #7073 (extern C exception boundary) -- check if clip.cpp at tools/mtmd/clip.cpp still has the issue
3. Build trust before attempting features

## Pipeline notes

- New contributor limit: 1 open PR at a time (per CONTRIBUTING.md)
- Bug fixes only until 3+ merges earned
- AI disclosure required if used for code generation
