# Hypothesis graph: njbrake/agent-of-empires#1227

## Issue
Cockpit: acceptEdits mode still triggers approval cards for Write/Edit. Adapter `canUseTool` only short-circuits `bypassPermissions`, not `acceptEdits`. Filed 2026-05-18 by @Seluj78.

## H₀ — Halt: contributor-self-PR pattern (confirmed, killed PR path)

**Hypothesis.** Issue reporter is a heavy repo contributor preparing to ship the fix themselves; an external PR here is duplicate effort and burns reviewer attention.

**Evidence (provenance check, Phase 2.5):**
- Seluj78 has 35 contributions to njbrake/agent-of-empires (vs maintainer njbrake at 561). Regular contributor.
- Issue body is a complete root-cause analysis: exact file/line refs (`src/cockpit/acp_client.rs:3020-3055`, `dist/acp-agent.js:1015-1090`), four explicit proposal options (A pin adapter / B aoe-side proxy / C settings TUI parity / D upstream tracking), and a list of "Open questions" the author intends to resolve.
- Author filed upstream tracking issue `agentclientprotocol/claude-agent-acp#685` the same day. They are actively driving both ends.
- Related open PR #1236 by Seluj78 — `feat(cockpit): surface set_mode rejection` — adjacent surface (mode handling in cockpit), same week.
- Issue note: "Idea, decisions, and everything else are mine. — @Seluj78". Owner-of-fix register.

**Trajectory shape.** Divergent against shipping. Every signal points to "author owns the fix."

**Edge.** Halt before Phase 5 (prework). No PR from us.

**Reasoning mode.** Deduction over pack contents; confidence ~95%.

## Decision

Route as **drop** (not investigate). The contributor-self-PR halt rule from memory ([[feedback_maintainer_self_pr]]) applies cleanly. The author has the diagnosis, the options, an upstream issue, and an adjacent PR in flight; the field is occupied.

If a tissue is warranted at all, it would only be "we observed the same in N sessions" — but the issue already cites concrete event-DB seq numbers from a real session, so even that adds nothing.

## Frontier
None. Closed.
