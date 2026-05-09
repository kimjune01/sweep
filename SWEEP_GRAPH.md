# Sweep Graph (2026-05-09)

**Mode:** dry-run
**Repos:** 10 (at cap). 7 active, 1 dormant, 1 pending review, 1 pending schema.

## Unified Punch List

### AWAITING REVIEW (2 PRs)

| Repo | # | Title | Score | Status | Next step |
|------|---|-------|-------|--------|-----------|
| gemini-cli | 24736 | union-find context compaction | 7/10 | Community LGTMs, needs rebase + ContextProcessor refactor | Rebase, refactor, wait (~May 14) |
| compiler | 1162 | strip dead imports for client:only | 9/10 | Changeset added, CI pending maintainer approval | Wait — ping ~May 14 |

### ACTIONABLE ISSUES (12 issues across 4 repos)

Quick wins to build merge history while waiting on existing PRs.

| Repo | # | Title | Jittered | Effort | Signal |
|------|---|-------|----------|--------|--------|
| **aider** | **3702** | **--no-verify-ssl fails for gemini/openrouter** | **8.45** | **Small** | **paul-gauthier labeled "priority"** |
| **prettier-plugin-astro** | **308** | **Formatter adds whitespace in expressions** | **8.45** | **Medium** | **Princesseuh confirmed, P4:important** |
| gemini-cli | 25693 | Skills discovery single-line SKILL.md | 7.16 | Small | Maintainer-labeled, good first issue |
| gemini-cli | 25689 | theme validation text.response | 7.16 | Small | Maintainer-labeled, good first issue |
| gemini-cli | 25459 | UI jank high-volume shell output | 7.16 | Medium | Maintainer-labeled help wanted |
| compiler | 1091 | Backslash escaped in tag attribute | — | Small | Exact file+line (printer.go#L474) |
| compiler | 1139 | Server islands + Astro.self | — | Medium | Same import-tracking code as #1162 |
| **mvdan/sh** | **813** | **BinaryNextLine for test/arith expressions** | **5.72** | **Medium** | **Maintainer help-wanted, Go AST** |
| **mvdan/sh** | **1233** | **zsh associative array key mangling** | **5.72** | **Medium** | **Maintainer help-wanted, parser bug** |
| compiler | 1096 | Nested lists wrong order with slots | P4 | Medium | Playground repro |
| compiler | 1116 | DOM corruption in `<td>` conditionals | P3 | Medium | Related to #958, #1015 |
| compiler | 1068 | Whitespace after style hoist | P3 | Small | Former maintainer acknowledged |

**Bold = new this tick.** Top 3 by jittered score: aider #3702, prettier-plugin-astro #308, gemini-cli #25693.

### READY TO SHIP (tinygrad cooldown until May 22)

| Repo | # | Title | Lines | Viability |
|------|---|-------|-------|-----------|
| tinygrad | 12296 | max backward underflow (float16) | net-zero | STRONG |
| tinygrad | 6909 | bf16 autocast ClangRenderer | +4 | OK |
| tinygrad | 13179 | Variable expression equality | +1 | OK |
| tinygrad | 11908 | Beam cache env var invalidation | +8 | OK |

### IN PROGRESS

| Repo | # | Title | Status |
|------|---|-------|--------|
| tinygrad | 13409 | ScatterND infinite loop | Needs scatter primitive or chunked workaround |

### CONFIRMED BUT BLOCKED

| Repo | # | Title | Blocker |
|------|---|-------|---------|
| tinygrad | 7020 | TinyJit wrong values | +10 lines, runtime overhead trade-off |

### STALE (ping signal)

| Repo | # | Title | Last activity |
|------|---|-------|---------------|
| Soar | 581 | soar-eval harness | Apr 12 |
| Soar | 577 | rl EMA low-update trigger | Apr 9 |

### MONITORING

| Repo | Item | Title | Status |
|------|------|-------|--------|
| cpython | #149575 | JIT exec() tracing PR | 0 reviews — ping Brandt Bucher |
| cpython | #139109 | Trace recording JIT (umbrella) | Active, 12 comments |
| cpython | #149212 | unpack_sequence slower under JIT | Monitor |
| faster-cpython | #739 | tinygrad benchmark proposal | No comments yet |

### DORMANT

| Repo | Reason |
|------|--------|
| withastro/astro | PR #16634 self-closed, superseded by compiler #1162 |

## Cross-repo Findings

### Context compaction (gemini-cli ↔ aider)
- gemini-cli#24736 (union-find context compaction) — same concept as aider PRs #4940/#4941 (rejected). If gemini-cli lands, provides precedent. Aider#3702 is a separate issue (SSL bypass) — builds trust for future context-compaction retry.

### Astro ecosystem cluster (compiler ↔ prettier-plugin-astro)
- compiler#1162 (strip dead imports), compiler#1139 (Astro.self), prettier-plugin-astro#308 (whitespace in expressions). Three repos in the same org, same maintainers (Princesseuh reviews all). Merge history in one helps get reviews in the others.

### Compiler import tracking (compiler #1162 → #1139)
- PR #1162 (strip dead imports) and issue #1139 (Astro.self server islands) share the same import-tracking code path.

### Go AST (compiler ↔ mvdan/sh)
- withastro/compiler is Go (print-to-js.go, HTML parser). mvdan/sh is Go (shell parser/formatter). Same skill: AST manipulation, printer bugs, node traversal. Experience transfers.

### bf16 cluster (tinygrad-internal)
- #6909 (autocast) ↔ #11756 (numerical exp/log/cos) ↔ #16114 (PTX KeyError, closed)

### CPython ↔ tinygrad perf
- cpython#149564 (JIT exec() tracing) → faster-cpython#739 (tinygrad benchmark).

### JIT correctness (tinygrad-internal)
- #7020 (wrong values) ↔ #6803 (bad SDXL output) — same root cause (output tensor aliasing)

## Per-repo Summaries

### google-gemini/gemini-cli
**Status:** 1 open PR (#24736), 4 actionable issues. Merge rate 1/5 (20%). 103K stars.
**Strategy:** Rebase #24736. Pick up #25693 as quick win.

### withastro/compiler
**Status:** 1 open PR (#1162), 5 actionable issues. Slow review (1-5 weeks).
**Strategy:** Wait for #1162 (~May 14 ping). Queue #1139, #1091.

### Aider-AI/aider (NEW)
**Status:** #3702 labeled "priority" by paul-gauthier. 44.5K stars. Previous PRs rejected but this is issue-first.
**Strategy:** Investigate #3702 (SSL bypass scope). Small fix, clear acceptance criteria.

### withastro/prettier-plugin-astro (NEW)
**Status:** #308 confirmed P4:important by Princesseuh. 598 stars, same org as compiler.
**Strategy:** Pending schema review. Fix builds Astro merge history.

### mvdan/sh (NEW — pending review)
**Status:** #813 and #1233 maintainer-labeled help-wanted. 8.7K stars, solo maintainer.
**Strategy:** Cold discovery — needs human approval. Go AST skill match.

### tinygrad/tinygrad
**Status:** Cooldown until 2026-05-22. Ban warning active. 4 fixes ready.
**Strategy:** Drip starting May 22. Lead with #12296.

### SoarGroup/Soar
**Status:** 2 stale PRs, zero engagement.
**Strategy:** Ping maintainers. Low priority.

### python/cpython
**Status:** Issue #149564 open, PR #149575 has 0 reviews.
**Strategy:** Ping JIT maintainer.

### faster-cpython/ideas
**Status:** Issue #739, no comments.
**Strategy:** Low-touch monitoring.

### withastro/astro
**Status:** Dormant.

## Diversity Matrix

| Repo | Language | Domain | Org size | Issue type |
|------|----------|--------|----------|------------|
| tinygrad | Python | ML compiler | medium | correctness, perf |
| gemini-cli | TypeScript | devtools/CLI | large | bug, feature |
| compiler | Go | web compiler | medium | bug |
| aider | Python | devtools | large | bug |
| prettier-plugin-astro | TypeScript | web tooling | medium | bug |
| mvdan/sh | Go | shell parser | solo | bug |
| cpython | C/Python | runtime | large | perf |
| Soar | C++/Java | cognitive arch | small | feature |

5 languages, 6 domains, 4 org sizes. No correlated cluster dominates.

## Jittered Actionable Results (2026-05-09, tick 2)

5 agents, each with shell-generated jitter. 15 candidates scored, 3 selected, 5 deduped (already tracked), 7 skipped (wrong domain, self-assigned, double risk).

| Agent | Bias | Jitter | Top pick | Score |
|-------|------|--------|----------|-------|
| 1 (Python/ML) | Python, systems | 1.056 | aider #3702 | 8.45 |
| 2 (TS/devtools) | TypeScript, CLI | 1.023 | gemini-cli #25693 (dup) | 7.16 |
| 3 (Go/compilers) | Go, parsers | 0.715 | mvdan/sh #813 | 5.72 |
| 4 (correctness) | any, bugs | 0.829 | stanza #1562 (skipped) | 5.80 |
| 5 (Rust/systems) | Rust, infra | 0.866 | rust-analyzer #22140 (skipped) | 6.06 |

---

*Dry run — no PRs pushed, no drip queues advanced.*
