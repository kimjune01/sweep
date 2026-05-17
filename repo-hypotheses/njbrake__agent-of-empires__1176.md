# njbrake/agent-of-empires#1176 — Cockpit "Force end turn" surfaces during subagent execution

**Issue:** https://github.com/njbrake/agent-of-empires/issues/1176
**Reporter:** @Seluj78 (Jules Lasne — active contributor, not the repo owner; Claude-assisted writeup disclosed in the issue body)
**Maintainer:** @njbrake
**Repo policy:** MIT, no LLM ban (project is itself a tool for managing LLM agents). Claude-authored prose welcome with attribution.
**Existing PRs:** none for this issue. @Seluj78 has unrelated open PR #1179. Search of `gh pr list ... 1176` returns empty.
**Adjacent:** #1100 (introduced force-end-turn watchdog), #1112 (Waiting-on-model badge), #1041/#1043 (subagent rendering — canonical misfire surface).

## Pre-investigation note: the issue body is already a hypothesis graph

@Seluj78's writeup contains: root cause (line-cited), three candidate fixes (A/B/C), kill conditions, open questions. Phases 1–3 are pre-done. This document is **Phase 2.5 (provenance check)** + **pushout disagreement scan** + **Phase 4.5 reframe test** + **Phase 5 prework gate**. Same posture as the sister investigation `njbrake__agent-of-empires__1177.md` (also reporter @Seluj78, also Claude-assisted writeup, also validation-only pass).

## H₀ — `showForceEnd` gate is purely time-based and ignores `inFlightTool`

**Claim.** `web/src/components/cockpit/CockpitView.tsx:818` sets `const showForceEnd = showStalled;` where `showStalled = stalledSecs >= forceEndTurnThresholdSecs` (default 30s). The `tool` parameter is in scope (line 753, 758, used by `chooseVerb` at 805) but never gates visibility. The watchdog therefore surfaces whenever streaming silence exceeds 30s, regardless of whether a tool — including a `Task` subagent that emits sparse frames between its child tool calls — is legitimately running.

**Trajectory:** divergent-for (deduction from code reading, lines verified).

**Provenance check (validated against `/tmp/aoe-1176` shallow clone at HEAD):**

- `web/src/components/cockpit/CockpitView.tsx:751-818` — `WorkingSpinner` signature includes `tool`, but `showForceEnd = showStalled` ignores it ✓
- `web/src/components/cockpit/CockpitView.tsx:266-272` — caller wires `tool={state.inFlightTool?.name ?? null}` ✓
- `web/src/hooks/useCockpit.ts:743` — every WS frame bumps `lastActivityRef.current = Date.now()` ✓ (heartbeat is per-frame, not tool-aware)
- `web/src/hooks/useCockpit.ts:864` — `dispatchPromptNow` bumps heartbeat on submit (avoids cold-start misfire) ✓
- `web/src/components/cockpit/CockpitRuntime.tsx:391` — subagent child tool calls smuggle `_aoe_parent_tool_call_id` ✓
- `src/cockpit/acp_client.rs:1580-1648` — subagent linkage via `_meta.claudeCode.parentToolUseId` ✓ (the issue's line cite 1346-1414 is slightly off — the real range is 1580-1648 — but the mechanism is real)

All cited code matches except the one off-range cite, which is non-load-bearing.

**Origin commit.** `git log` on `CockpitView.tsx` around the WorkingSpinner block traces to #1100 (the force-end-turn introduction). The watchdog was added to recover from a wedged spinner *before* subagent rendering (#1041/#1043) landed; subagents weren't on the threat model when the gate was designed. Confidence: deduction, 95%.

## H₁ — Subagent thinking produces no frames on the AoE side

**Claim.** Between subagent child tool calls, the subagent's reasoning is internal to claude-agent-acp and does not produce frames that bump `lastActivityRef`.

**Verification (partial).** `is_transcript_event` at `acp_client.rs:1396-1414` lists `ThinkingStarted`/`ThinkingEnded` as transcript events — but the issue claims claude-agent-acp doesn't *emit* these for subagent loops, only for the main loop. I can't fully verify without reading claude-agent-acp's source; the AoE-side handler is set up to relay thinking if it arrives. The behavioral evidence in the issue (30s+ gaps between subagent child tool calls trip the watchdog) is consistent with the claim.

**Trajectory:** convergent (deduction + behavioral evidence in issue; 85% — the AoE-side claim is verifiable from the open-source claude-agent-acp adapter and worth a one-line confirmation during prework).

## Pushout — disagreement scan against the reporter's recommendation

The reporter recommends **(A)** alone as the minimal fix: `const showForceEnd = showStalled && tool == null;`. **(B)** layers subagent-aware labeling. **(C)** is dismissed (heartbeat tweak — not needed). My read:

### Where I agree

- **(A) is the smallest correct fix.** One line, well-isolated, covers the reported failure mode. The `tool` prop is already plumbed; no new state required. Roughly:
  ```ts
  const showForceEnd = showStalled && tool == null;
  ```
- **(B) variant 3 (suppress button entirely while subagent in flight) collapses to (A)** — once any in-flight tool suppresses the button, distinguishing Task from Bash for visibility is moot.
- **(B) variant 2 (better verb)** is a labeling improvement, separable. The current "Waiting on model… 1m 23s" is misleading when the model is downstream of a running tool. A new verb "Tool running… 1m 23s" (or "Subagent running… 1m 23s" when `inFlightTool.name === "Task"`) is worth landing in the same PR — same file, same component, trivial cost.
- **(C) is correctly dismissed.** Heartbeat is already bumped on every frame including subagent child tool calls. The bug is on the visibility side, not the heartbeat side.

### Where I'd push back

**The "wedged tool" gap is bigger than the reporter acknowledges.** The reporter's mitigation for losing force-end during in-flight tools is: "Stop button still works." But Stop kills the whole turn and any earlier progress. Force-end-turn was a softer signal — "watchdog noticed silence." After (A), if the agent process *crashes* between emitting `ToolCallStarted` and any subsequent event (e.g., OOM kill during a long Task, segfault in a tool runner), `state.inFlightTool` is stuck non-null forever. Verified by reading `cockpitTypes.ts` — `inFlightTool` is cleared in exactly three paths:

  - `ToolCallCompleted` matching id (line 495-496)
  - `Stopped` (line 642)
  - `AgentStartupError` (line 692)

No clearing on WS disconnect, no timeout-based reset, no "agent died mid-tool" path. So with (A) applied, the watchdog becomes silently *unavailable* in the exact scenario it was designed to handle. The reporter's writeup doesn't address this.

**Mitigations to consider before shipping (A):**

1. **Two-tier threshold.** Suppress force-end-turn while `tool != null` and `stalledSecs < N * forceEndTurnThresholdSecs` (e.g., N=4 → 120s default). After that hard ceiling, surface the button even with a tool in flight. The label can still say "Tool running…" but the escape hatch reappears. This is a few extra lines and covers the wedged-tool case without ramifying config.
2. **Clear `inFlightTool` on WS reconnect after lagged-frame recovery.** Already partially handled via the snapshot endpoint, but worth verifying that the snapshot resets `inFlightTool` when the agent has actually completed work the WS missed. If the snapshot is authoritative, the wedged-tool case may already be covered.
3. **Ship (A) alone, accept the wedged-tool gap, and add a follow-up issue** describing the crash-mid-tool case. Smallest diff; matches the reporter's preference.

My recommendation: **ship (A) alone in the spirit of the reporter's preference, but flag option 1 (two-tier threshold) in the PR description as a follow-up.** The wedged-tool scenario is rarer than the false-positive misfire (#1176's actual complaint), and a small follow-up is cheaper than a contested PR.

**Verb-update bonus.** While touching `WorkingSpinner`, fix the misleading label for the in-flight-tool case:

```ts
const label = showStalled
  ? (tool ? `${tool === "Task" ? "Subagent" : "Tool"}… ${formatElapsed(stalledSecs)}`
          : `Waiting on model… ${formatElapsed(stalledSecs)}`)
  : chooseVerb(state, seed, tool);
```

Cost: 2 extra lines, no new state, no new config. Strictly clearer than the current "Waiting on model…" lie when a Task is running.

## Frontier edges

1. **Crash-mid-tool wedged-button scenario.** Does the snapshot endpoint (`fetchReplay`) clear `inFlightTool` when an agent died mid-Task? *Predicted classification:* convergent if the snapshot reducer hits `ToolCallCompleted`/`Stopped`; divergent (gap exists) otherwise. Worth a unit test before shipping (A).

2. **Does claude-agent-acp emit `ThinkingStarted`/`ThinkingEnded` for subagent loops?** The issue claims no. If yes, a richer fix would forward subagent thinking through the existing `ThinkingStarted` event and the watchdog stays useful at subagent granularity. *Predicted classification:* convergent on "no" (per the issue) but worth a 5-min source check in the adapter.

3. **Should `state.thinking` factor in?** Currently `showForceEnd = showStalled` ignores both `thinking` AND `tool`. Should it also be suppressed when `thinking === true`? Arguably yes for symmetry — if the model is mid-thinking-block, that's not a wedged turn either. Reporter didn't raise this. Worth a one-line addition: `const showForceEnd = showStalled && tool == null && !thinking;`. Confidence: abduction, 70%.

4. **Substrate switch and prefs reload.** `forceEndTurnThresholdSecs` comes from `useCockpitPrefs()`. If the user has set this very low (e.g., 10s) to be aggressive about wedged-detection on idle agents, (A) suppresses force-end longer than they configured during long tool runs. Acceptable — the prefs gate the *time*, the new gate adds a *condition*. Worth mentioning in the PR description.

## Reframe test (Phase 4.5)

Does the surviving hypothesis answer the original question, or replace it? **Answers.** "Why does force-end surface during subagent execution?" → "Because the gate ignores `inFlightTool`." Fix follows mechanically. No reframe; straightforward gate refinement.

## Decision: prework + readiness, do not ship without maintainer approval

Same posture as `#1177`: @Seluj78 is a co-contributor who already did the diagnostic work. The polite path is to **comment on the issue with the validation + the wedged-tool pushback**, leaving room for the reporter to land the fix themselves. The maintainer (@njbrake) will pick whoever they prefer.

**If the maintainer or reporter wants a PR from this account**, prework is trivial:

- **Branch:** `fix/cockpit-force-end-turn-tool-gate` (matches `fix/` convention).
- **Change:** one line at `web/src/components/cockpit/CockpitView.tsx:818` + 2 lines for the verb update.
- **Test:** unit test for the gate logic in a new `WorkingSpinner.test.ts` (or extend existing `cockpitTypes.test.ts`): `showForceEnd === false when tool !== null && showStalled`, `showForceEnd === true when tool == null && showStalled`. The repo has a Vitest setup and existing unit tests for `cockpitTypes`, so the harness is in place.
- **Manual verification before PR:** run a long Task subagent (e.g., "explore this codebase"), confirm button stays hidden during sparse-frame thinking gaps, confirm label is "Subagent… Xm Ys" instead of "Waiting on model… Xm Ys", confirm button still surfaces when the parent is idle (no `inFlightTool`).
- **PR body:** link #1176 (closes), reference #1100 (origin), describe the wedged-tool gap as a known follow-up.

## Graph state

| Node | Status | Mode | Confidence |
|---|---|---|---|
| H₀: `showForceEnd` ignores `inFlightTool` | confirmed | deduction (line-verified) | 99% |
| H₁: subagent thinking emits no frames | confirmed | deduction + behavioral evidence | 85% |
| Origin: gate from #1100, pre-subagent threat model | confirmed | provenance (gh) | 90% |
| Fix shape (A): `showStalled && tool == null` | proposed | deduction | 95% |
| (B) verb update bundled with (A) | proposed | deduction | 90% |
| (B) variant 3 (suppress on Task only) | argued against (collapses to A) | deduction | 80% |
| (C) heartbeat tweak | argued against (issue is on visibility side) | deduction | 90% |
| Pushback: wedged-mid-tool gap after (A) | open | deduction + missing data on snapshot reducer | 80% |
| Frontier 1: snapshot reducer clears `inFlightTool` on crash | open | needs unit test or trace | — |
| Frontier 2: claude-agent-acp subagent thinking emission | open | needs adapter source check | — |
| Frontier 3: also gate on `thinking` for symmetry | open | abduction | 70% |

## Halt reason

Hypothesis-grounded; fix shape is one line plus a verb update; PR-shaped change but **author etiquette favors commenting on the issue with the validation + wedged-tool pushback rather than racing the reporter to a PR**. Awaiting human go/no-go on (i) post a validation comment on #1176, (ii) open a PR ourselves, (iii) do neither and let @Seluj78 / @njbrake handle it. Default: (iii) unless the user instructs otherwise — the reporter has been doing high-quality writeups and likely intends to ship the fix himself.
