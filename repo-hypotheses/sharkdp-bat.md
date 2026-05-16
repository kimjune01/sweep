# Triage Graph: sharkdp/bat (kimjune01)

**Scan date:** 2026-05-09
**Repo profile:** Rust CLI (cat replacement), 59K stars, solo maintainer (sharkdp), two active collaborators (keith-hall, eth-p)

## Scan Table

| # | Title | Labels | Score | Effort | Signal | Status |
|---|-------|--------|-------|--------|--------|--------|
| 3733 | Forced colors/decorations config corrupts zsh completions | bug | 8/10 | Tiny (3 lines) | Reporter provided exact fix | COMMITTED |
| 1618 | --list-themes + BAT_OPTS problematic | bug, good-first-issue | -- | -- | Fixed by #3457 | CLOSED (resolved) |
| 1341 | Custom fallback syntax opt-in | feature-request, good-first-issue | -- | -- | Active PR #3617 by Xavrir | CONTESTED |
| 3710 | --decorations=auto shows decorations when piped + --color=always | bug | 6/10 | Medium | Competing PR #3719 | CONTESTED |
| 3660 | --no-paging still wraps when piped | bug | 5/10 | Medium | 0 comments, complex interaction | OPEN |
| 3559 | Help text ignores custom theme | bug | -- | -- | Fixed by #3524 (unreleased) | CLOSED (resolved) |
| 3641 | --theme auto falls back to default | bug | 4/10 | Complex | tmux-related, likely terminal detection | OPEN |
| 3554 | Encrypted file not recognized as binary | bug | 4/10 | Medium | Needs upstream crate change | OPEN |
| 3444 | ctrl-c exits less despite no --quit-on-intr | bug | 3/10 | Complex | 18 comments, design disagreement | OPEN |

## I3733: zsh completion corruption from forced colors/decorations

### Root Cause

The zsh completion script calls `bat --list-languages` and `bat --list-themes` to populate tab-completion candidates. When `BAT_OPTS` contains `--color=always` or `--decorations=always`, these commands emit ANSI escape codes that corrupt the completion output, inserting garbage like `$'\033'[32m...` into the prompt.

### Fix (3 lines)

Pass `--color=never --decorations=never` in all three completion callsites in `assets/completions/bat.zsh.in`:
- `--list-languages` call (line 93)
- `--list-themes` call for `--theme-dark`/`--theme-light` (line 100)
- `--list-themes` call for `--theme` preferences (line 106)

### Prior attempts

Issue filed 2026-05-08. Reporter cited #2897 (2024, same symptom different cause) and noted that PR #3704 (merged 2026-04-27, fixed word-splitting) did not address this variant. No prior PRs targeting this specific escape-code leakage path.

### PR Viability: HIGH

**For:**
- Bug-labeled, clear reproduction, exact fix provided by reporter
- Zero code complexity: pure shell script, no Rust changes
- No design decisions involved -- the completion script should never emit escape codes
- keith-hall (collaborator) is actively reviewing PRs and closing issues (recent: #3704, #3661, #3524)
- bat merges external PRs regularly: #3704, #3708, #3719, #3725 all open/merged in past 2 weeks

**Against:**
- Solo maintainer (sharkdp) has long review cycles -- many PRs sit for weeks
- fish and bash completions have the same vulnerability but are out of scope for this PR

### Competing PRs

None.

### Commit

Branch `fix/zsh-completion-force-plain` on `kimjune01/bat`, commit a0c95618.

---

## Repo Dynamics

- **Merge velocity:** Moderate. ~5 PRs merged per month. Dependabot PRs land quickly. External bug fixes merge in 1-4 weeks.
- **Gatekeeper:** keith-hall (COLLABORATOR) reviews most PRs. sharkdp (OWNER) does final merge.
- **PR density:** ~45 open PRs, many stale (6+ months). High volume of drive-by docs/deps PRs.
- **Bug fix track record:** Bug-labeled issues with clear fixes merge reliably. Feature requests stall unless a collaborator endorses.
- **AI policy:** No explicit AI disclosure requirement in PR template, but good practice to disclose.

---

*Generated 2026-05-09. One PR queued in drip pipeline.*
