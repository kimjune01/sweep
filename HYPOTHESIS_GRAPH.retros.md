# Hypothesis graph — retros & investigations

Dated session retros and one-off investigations split out of
[HYPOTHESIS_GRAPH.md](./HYPOTHESIS_GRAPH.md). Append-only narrative;
each entry is a snapshot in time. The live graph carries the current
claims; this file carries the trail.

## 2026-05-10: dbg-macro #142 (sharkdp org, second repo)

**Issue:** CMake deprecation warning for versions < 3.10. 1 comment (maintainer "Sounds good").

**Triage decision:** Smallest issue among 5 open. Rejected #144 (Windows OutputDebugString - platform-specific), #137 (complex feature), #131 (Eigen integration, 7 comments), #109 (variadic templates, 8 comments, unsolved).

**Implementation:** Changed `cmake_minimum_required(VERSION 3.5)` to `VERSION 3.5...3.10`. Range syntax sets policy version to 3.10 (suppresses warning on CMake 3.31+) while maintaining minimum at 3.5 (backward compatible).

**Quality gates:**
- **Codex review:** Caught initial mistake (3.10...3.30 raises minimum to 3.10, breaks users). Corrected to 3.5...3.10. Explained range syntax semantics (min vs policy version).
- **Gemini review:** Confirmed backward compatibility, identified policy changes (CMP0068, CMP0067, CMP0071), assessed risk as very low. Verified CMake 3.0-3.11 parse range as VERSION 3.5.


**Drip queue:** Added. Ready to push (waiting on binocle to land or timeout).

**Competing PRs:** Zero. Confirmed with `gh pr list`.

## 2026-05-10: prometheus/statsd_exporter #552 (queued)

**Issue**: Rate-limited logging for parsing errors  
**Hypothesis**: H2 (maintainer-acknowledged + detailed spec)  

**Signals**:
- Maintainer (matthiasr) provided detailed implementation spec in comment
- "help wanted" label
- Clear acceptance criteria (rate limit by cardinality, default 1/min, track suppressed count)
- Maintainer specifically requested distinct messages for duplicate error sites

**Implementation**:
- 3 files changed: rate_limited_logger.go (85 lines), tests (151 lines), integration (24 edits to line.go)
- Codex approved with structural improvements (implemented)
- Gemini flagged potential issues (all mitigated or acceptable for this use case)
- All tests pass

**Status**: Commit 5fd17eb queued in drip, awaiting push per user instruction

**Prediction**: High merge probability (>80%) given maintainer spec + help-wanted label

## Session 4 retro (2026-05-11)

### New merges: xtend_tuya #930, pertpy #965

**xtend_tuya #930** (322 stars, Python, Home Assistant integration)
- 6-line addition to const.py disambiguating battery dpcodes
- Merged in <2 hours, zero comments from maintainer
- H0: PASS (code quality sufficient), H5: PASS (solo maintainer, boring fix), H8: STRONG (trivial complexity = instant merge)

**pertpy #965** (310 stars, Python, perturbation analysis)
- Fixed seaborn heatmap tick label visibility defaults
- Merged same day, gemini review PASSED pre-ship (batch 1)
- H0: PASS, H1: PASS (issue-first), H8: PASS (small fix), first contribution to scverse org

### Session 4 pipeline findings

**Gate bypass incident:** 22 PRs shipped without gemini review. Post-ship gemini review caught 7 critical bugs (27% failure rate). All fixed before maintainer review. Lesson: gates are not optional. The gate hook now rejects NOT_RUN verdicts and requires first/last sentence receipts.

**Bug taxonomy from gemini:**
- Memory safety (amsynth double-free): agent didn't understand JUCE modal dialog lifecycle
- Platform assumptions (osctrl sudo domain): agent didn't test non-root execution path
- Spec compliance (slang-server delimiters): agent used fixed delimiter instead of dynamic per CommonMark
- Index safety (octave -1 parent): agent introduced regression by changing unsigned comparison semantics
- Logic errors (sysidentpy double bias): agent didn't understand existing bias column from build_lagged_matrix
- Streaming regression (ffs buffering): agent replaced streaming with buffering for simplicity
- Edge cases (sekai-viewer undefined skill): agent didn't guard filter()[0] return

**Pattern:** 5/7 bugs were about not understanding the existing code's invariants before changing it. The devil's advocate gate ("why does the current code do it this way?") would have caught octave and sysidentpy. The others needed domain knowledge the agent lacked.

**H10 (proposed): Gemini review catches bugs that triage agents introduce**
- Prediction: gemini adversarial review on the diff catches 20-30% of bugs that sonnet triage agents produce
- Evidence: 7/22 = 32% failure rate on session-4 PRs (sonnet agents, no pre-ship review)
- Falsification: if opus agents produce the same failure rate under gemini review, the bug rate is intrinsic to the fix complexity, not the model

**TDD compliance: 2/11 (18%)**
- Only conserve and slang-server had separate test commits
- Root cause: sonnet agents optimize for task completion over process compliance
- Fix: triage model changed from sonnet to opus for session 5
- Prediction: opus TDD compliance will be >50%

### Score (2026-05-12, retro)

| Metric | Value |
|--------|-------|
| Open PRs | 103 |
| Merged | 15 |
| Closed (unmerged) | 28 |
| Merge rate (raw) | 15/43 = 35% |
| Merge rate (adjusted) | 15/27 = 56% |
| Session-4 PRs shipped | 22 |
| Session-4 PRs merged | 2 (xtend_tuya, pertpy) |
| Session-4 gemini bugs | 7 (all fixed) |
| Pre-reg accuracy | 5/6 = 83% |
| Repos on roster | ~150 triaged, ~30 evicted |

### Score (2026-05-11, retro)

| Metric | Value |
|--------|-------|
| Open PRs | 119 |
| Merged | 15 |
| Closed (unmerged) | 29 |
| Merge rate (raw) | 15/44 = 34% |
| Merge rate (adjusted) | 15/27 = 56% |
| CONTRIBUTING.md failures | 5 (open-webui ×3, immich, litestar) |
| Triage batch output | 16 new PRs shipped (session 6) |
| Repos on roster | 523 total, 264 ready, 180 triaged, 45 evicted |
| Org gate backlog | 86 QA'd entries blocked |

## Investigation: zulip/zulip fix-klipy-locale (drip-queue stale entry, 2026-05-14)

**Trigger:** `~/.sweep/drip-queue/zulip-zulip.jsonl` contains a 2026-05-13T04:44 entry on branch `fix-klipy-locale` (no `-format` suffix), status=triaged, reason="review backflow: fix locale code handling per maintainer feedback". Subsequent entries on same date moved to `fix-klipy-locale-format` (PR #39265). The bare `fix-klipy-locale` entry remained un-shipped.

### H₀: the triaged entry is a fresh actionable item
- **Null:** the entry is duplicate provenance for work already shipped on `fix-klipy-locale-format` (PR #39265).
- **Perturbation:** `git branch -a | grep klipy` in /Users/junekim/Documents/zulip; `gh pr list --repo zulip/zulip --search klipy --state all`.
- **Evidence:** Local repo has only `fix-klipy-locale-format` (no bare `fix-klipy-locale` branch). Remote search returns TWO open PRs for #39202: #39265 (ours, `fix-klipy-locale-format`) and #39284 (`fix-klipy-locale`, author `apoorvapendse` — the COLLABORATOR who reviewed our PR).
- **Trajectory:** Divergent against H₀. The branch name `fix-klipy-locale` is occupied by a competing PR from a Zulip collaborator, not a stale internal branch.
- **Status:** killed.
- **Edge:** classify the duplicate-fix collision (H₁).

### H₁: collision is harmless duplicate (we co-fix the same bug)
- **Null:** collision damages standing or wastes pipeline budget per H16 (alt-fix-preempted).
- **Perturbation:** read both PR conversations side by side, compare approaches and reviewer engagement.
- **Evidence:**
  - PR #39284 (apoorvapendse, COLLABORATOR, opened 2026-05-12T19:04:47Z) — manual `xx_YY` underscore mapping, `Tested locally for en-gb, zh-hans, Welsh, en-us`. Reviewer karlstolley asks "is there a library?", apoorvapendse proposes `Intl.Locale.maximize()`, karlstolley confirms browser support is fine, apoorvapendse retests. Active convergence on a cleaner approach.
  - PR #39265 (kimjune01, NONE-association, opened earlier same day as commit 5c7adf65, then patched to BCP-47 hyphen mapping after apoorvapendse's drive-by review on #39265 itself). Hardcoded 51-locale enum table.
  - apoorvapendse reviewed BOTH PRs; the collaborator reviewed ours in passing and continued investing in their own. No standing damage observed (review was substantive and constructive), but maintainer attention is split.
- **Trajectory:** Convergent — this is exactly H16 (alt-fix-preempted): in-flight maintainer work overlapping our actionable-error fix, surfaced too late because the issue thread didn't show #39284 was already drafted.
- **Status:** confirmed. Third instance of H16 (after Jaxx497/NoctaVox#21 and feldera#6219).
- **Edge:** which fix lands?

### H₂: maintainer-authored PR #39284 wins the merge race
- **Null:** ours merges (or both merge as redundant fixes — Zulip won't merge two locale-rewrites).
- **Perturbation:** read review trajectory and standing asymmetry.
- **Evidence:**
  - apoorvapendse is `COLLABORATOR`; ours is `NONE`.
  - karlstolley (`CONTRIBUTOR`) is actively reviewing #39284, suggesting `Intl.Locale.maximize()`. No reviewer engagement on #39265 since our 2026-05-13 reply.
  - apoorvapendse's `Intl.Locale.maximize()` direction is architecturally cleaner than our hardcoded enum (karlstolley: "rather than a manually maintained list").
  - Klipy's actual locale enum (`en-GB, en-US, es-ES, es-419, ...`) is what BOTH PRs need to target. Ours hardcodes it. Theirs lets browser Intl handle the canonicalization with Klipy's documented `xx_YY` fallback behavior.
- **Trajectory:** Divergent against ours. Architectural taste + standing asymmetry + active maintainer engagement on competitor.
- **Status:** confirmed (high confidence by deduction; awaiting induction via merge outcome).
- **Edge:** what should the pipeline do with the bare-name drip entry?

### H₃: the bare `fix-klipy-locale` drip entry should be drained, not shipped
- **Null:** ship it (would create a third PR for the same bug under our authorship).
- **Perturbation:** check whether a remote branch `fix-klipy-locale` exists in our fork; check force-push/branch-collision risk.
- **Evidence:**
  - No local branch `fix-klipy-locale` exists. The drip entry has no commits to push.
  - The branch name on the upstream repo `zulip/zulip` is OWNED by apoorvapendse's PR #39284. Pushing our branch with the same name to our fork would not collide upstream, but ANY ship attempt would either no-op (no commits) or duplicate PR #39265.
  - Per [[feedback-batch-submission-detection]]: max 1 PR per repo per session, 48h cooldown. We already have #39265 active.
  - Per [[feedback-stale-pr-heuristic]]: stale entries are signal, not noise. This entry's signal is "the QA-revert at 04:50:07Z left the bare-name entry orphaned when the next iteration moved to `-format` branch."
- **Trajectory:** Divergent — ship is structurally a no-op or a duplicate. Drain.
- **Status:** confirmed.
- **Edge:** none. Frontier closes.

### Provenance
- **Origin commit:** 5c7adf65d1 (`gifs: Introduce KLIPY as a GIF provider.`) — the regression-introducing commit. Both fixes target it.
- **Upstream issue search:** zulip/zulip#39202 (the bug); apoorvapendse comment on #39265 cites Klipy migrate-from-tenor docs as authoritative source. Both PRs verified against same docs.
- **Adjacent clue synthesis:** apoorvapendse opened #39284 twelve hours before reviewing #39265 — meaning the COLLABORATOR was already mid-fix when our PR appeared. The H16 detection rule (`gh log --since=30d -- <touched files>`) would NOT have caught this, because #39284 was drafted, not committed to default branch. **Refines H16 detection:** also check `gh pr list --repo <r> --search "<file or symbol>" --state open` for in-flight work, not just merged commits.
- **Risk assessment:** standing-neutral so far. apoorvapendse engaged constructively on #39265. Continued push on #39265 risks crossing into "competing with the collaborator's PR" — eviction-class behavior.

### Diagnosis (TL;DR)
Drip-queue entry `fix-klipy-locale` is **stale orphan** from a 2026-05-13T04:50:07Z QA-revert that bumped the next iteration to `fix-klipy-locale-format` but left the original entry behind. Branch does not exist locally, is not push-able, and the bug it targeted is already addressed by our own PR #39265 — which is itself in race with collaborator-authored PR #39284 (`Intl.Locale.maximize()` direction). **Action: /drain this entry. Do not ship.** Consider closing #39265 with a comment deferring to #39284 if reviewer momentum continues there past 7 days (per H16 alt-fix-preempted handling).

### Reasoning mode table
| Claim | Mode | Confidence |
|---|---|---|
| Branch `fix-klipy-locale` does not exist locally | Induction (git branch) | 99% |
| PR #39284 exists and addresses #39202 | Induction (gh) | 99% |
| #39284 has reviewer momentum on `Intl.Locale.maximize()` | Deduction (read comments) | 95% |
| #39284 will merge before #39265 | Abduction (standing + taste) | 75% |
| Drip entry is QA-revert orphan | Deduction (read jsonl timestamps) | 95% |
| H16 detection rule needs `gh pr list` extension | Abduction | 70% |

### Pruning log
- H₀ killed by H₁ (induction: gh search returned competing PR).
- H₂ alternate "both merge" killed by deduction (Zulip won't accept two competing locale rewrites for one bug).

### Frontier
Closed. No open edges. Recommendation to drain encoded above.

