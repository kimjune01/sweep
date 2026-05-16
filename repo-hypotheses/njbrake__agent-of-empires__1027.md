# njbrake/agent-of-empires#1027 — cockpit capacity-full UX

**Issue:** capacity-full message shows wrong remediation, leaves orphan session, no slot visibility.
**Reporter:** @Seluj78 (also the cockpit-polishing PR-series owner).
**Investigated:** 2026-05-16. Repo cloned to `/tmp/agent-of-empires` at `main`.

## Halt — reframe at Phase 4.5

The investigation does NOT proceed to prework/ship. The reframe is that the issue is **already partially owned in-flight by the reporter**, and the remaining work hinges on a maintainer decision the maintainer has not given. A competing PR is negative-EV here.

## Causal chain

### H₀ — verify reporter's diagnosis is current

- **Perturbation:** read every referenced file location.
- **Trajectory:** divergent — diagnosis is mostly accurate, line numbers stale.
- **Findings:**
  - `StartupErrorBanner` lives at `web/src/components/cockpit/CockpitView.tsx:1275` (not 538-630). Code has moved.
  - `CapacityFull` enum at `src/cockpit/supervisor.rs:63`; 503 mapping at `src/server/api/cockpit.rs:177`.
  - Auto-spawn detach pattern at `src/server/api/sessions.rs:1010-1117` — still the "201 first, spawn in `tokio::spawn` later, orphan on failure" shape the issue describes.
  - Reconciler factored into its own file `src/server/cockpit_reconciler.rs`; uses an `attempted` set (line 147) so the same id isn't re-poked every 2s. The "republishes `AgentStartupError` every 2s" behavior the issue claims is **already mitigated**, not yet for `CapacityFull` specifically but for all failure modes.
- **Edge:** check which of the three proposed fixes (A, B, C) have shipped since the issue was filed.

### H₁ — Part A (banner branch for capacity) already shipped

- **Perturbation:** `git log -S "isCapacity" -- web/src/components/cockpit/CockpitView.tsx`.
- **Result:** commit `c505fbc` (PR #1040, "Cockpit polishing", by @Seluj78, merged 2026-05-12 — same day issue was filed). Adds `isCapacity = /capacity full|max_concurrent_workers/i.test(message)` branch with the prescribed remediation copy (raise `max_concurrent_workers` / free a slot / "reinstalling the adapter won't help").
- **Trajectory:** divergent — A is done by the reporter himself.
- **Provenance:** same author as the issue. He filed the bug and shipped layer A on the same day.

### H₂ — Part B (pre-check capacity at create, no orphan) not shipped

- **Perturbation:** read `create_session` cockpit-spawn block at `sessions.rs:1010-1117`.
- **Result:** still pushes the instance, then `tokio::spawn` the supervisor call, then on `Err(_)` calls `publish_startup_error`. No pre-check against `Supervisor::count() >= max_concurrent_workers` before the push. Orphan session shape is unchanged.
- **Open design question:** issue itself flags B-path-A (strict 503 at create) vs B-path-B (graceful tmux fallback) as a maintainer call. Maintainer @njbrake has not commented (comments=[] on the issue).
- **Trajectory:** divergent — work not done, but blocked on a decision that isn't an investigator's to make.

### H₃ — Part C (`GET /api/cockpit/workers`) not shipped

- **Perturbation:** grep route table in `src/server/mod.rs:1024-1064`.
- **Result:** no `/api/cockpit/workers` route. Routes present: `cockpit/ws`, `cockpit/spawn`, `cockpit` DELETE, `cockpit/files`, `cockpit/master`. None enumerate live workers.
- **Trajectory:** divergent — work not done. C is the cleanest of the three: smallest design surface, snapshot a `Vec<WorkerHandle>` field set, return JSON.

### H₄ — reporter is actively owning this area

- **Perturbation:** `git log --since="2026-05-10" --grep="cockpit"`.
- **Result:** Seluj78 authored at least PRs #1040, #1067 ("Cockpit polishing 2"), #1076 ("Cockpit polishing 3"), #1094 ("4"), #1115 ("5"), #1122, #1137 ("7"), #1153, #1154, #1155, plus the unmerged #1156. Eleven cockpit PRs in five days. He filed #1027 as his own roadmap, not a request.
- **Trajectory:** divergent — opening B or C as an outsider PR walks across his lane while he's mid-stride.

### H₅ — first-mover claim viable?

- **Test:** issue is P1, 4 days old, zero comments, reporter clearly self-assigning by shipping A. Phase 7.5 claim would either (a) collide with Seluj78's next PR or (b) require asking him "are you handling B and C?" before claiming.
- **Trajectory:** divergent against. The polite move is a comment confirming his ownership, not a claim.

## Reframe

Original H₀ was "diagnose capacity-full UX bug." The surviving observation is **the bug is a roadmap doc for the reporter's own PR series**. Three of three proposed fixes were authored as a single issue because they're staged work, not three independent bugs. Part A shipped same-day under the reporter's own hand. Parts B and C are blocked on maintainer answers to the four open questions at the bottom of the issue body — questions an outside contributor cannot resolve.

The transferable pattern: **when a reporter is also a high-velocity contributor in the same area, their multi-part issues are usually their own kanban**. Prospect should down-rank these unless the issue is explicitly tagged "help wanted" or the contributor has gone quiet for >2 weeks. Here, neither.

## Graph state

| Node | Status | Shape | Notes |
|------|--------|-------|-------|
| H₀ verify diagnosis | confirmed | divergent | Diagnosis valid; line numbers stale. |
| H₁ part A shipped | confirmed | divergent | PR #1040 by reporter, 2026-05-12. |
| H₂ part B status | confirmed | divergent | Not shipped; blocked on design Q. |
| H₃ part C status | confirmed | divergent | Not shipped; cleanest slice. |
| H₄ reporter ownership | confirmed | divergent | 11 cockpit PRs in 5 days. |
| H₅ claim viable | killed | divergent against | Would collide with reporter. |

## Frontier (closed)

No open edges. The investigation does not produce a PR.

## Decision

**Drop.** Do not push, do not claim, do not comment. Record in seen-issues. If the issue is still open and parts B/C are still unshipped after ~2026-06-15 (one month), reconsider — by then the reporter's burst will have either landed or stalled, and a comment offering to take Part C alone (the cleanest, design-cheapest slice) would be reasonable. Until then this is his to ship.

## Reasoning mode

- Deduction (read code, traced state): H₀, H₁, H₂, H₃ — 95% confidence.
- Induction (git log measurement): H₄ — 95% confidence.
- Abduction (social inference): H₅, reframe — 75% confidence. The "reporter owns this" pattern could be wrong if Seluj78 wants help; only a comment would settle it, and the cost of asking exceeds the cost of waiting.
