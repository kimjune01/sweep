---
issue: FancyWM/fancywm#447
title: "COMException REGDB_E_CLASSNOTREG after sleep wake — VirtualDesktopManager retry budget too small"
target_repo: FancyWM/winman-windows
investigated_at: 2026-05-16
status: diagnosis-converged
---

# Hypothesis Graph: FancyWM/fancywm#447

## Issue summary

After Windows wakes from sleep on Win11 build 26200 (Insider Beta), FancyWM's overlay update loop throws `COMException 0x80040154 REGDB_E_CLASSNOTREG` at `Win32VirtualDesktopService26100.Connect()`. The COM CLSID `{C2F03A33-21F5-47FA-B4BB-156362A2F239}` is Explorer's IServiceProvider for IVirtualDesktopManagerInternal on this build. Stack origin: `OverlayHost.UpdateLoop` → `TilingService.GetOverlayAnchor` → `Win32VirtualDesktopManager.GetCurrentDesktop` → `FaultTolerantWin32VirtualDesktopService.ExecuteWithRetry` (10 attempts).

Maintainer (veselink1) acknowledged the bug and pointed at `FaultTolerantWin32VirtualDesktopService.cs:100-125`, suggesting the 5s wait for Explorer is too short.

## H₀ — Baseline observation

**Hypothesis:** The unhandled COM exception in the dispatcher's UpdateLoop tears down the app.

**Perturbation:** Read `OverlayHost.cs` to confirm exception propagation path.

**Evidence:**
- `OverlayHost.cs:136-144` — `UpdateLoop` is `async void` (the canonical "fire and forget" footgun). Exceptions escape into `Task.<>c.<ThrowAsync>` (visible in trace) and reach the WPF dispatcher.
- `UpdatePositions()` calls `AnchorSource()` which resolves to `TilingService.GetOverlayAnchor` (per stack), which calls into the desktop service.
- No try/catch surrounds the call inside the loop.

**Trajectory:** Divergent — the propagation path is unambiguous.

**Edge:** Two distinct concerns surface:
- E1: Retry budget upstream (winman-windows) is insufficient
- E2: Update loop is fragile to *any* single transient failure
Both are real. Maintainer prefers E1 path; investigate both.

## H₁ — Retry budget insufficient after sleep-wake (E1)

**Hypothesis:** `ExecuteWithRetry` gives up after 10 × 500ms ≈ 5s. After resume, Explorer's IServiceProvider for VDM can take longer to re-register on Win11 26100+ (the build that introduced `Win32VirtualDesktopService26100`).

**Null:** Retries persist but Explorer never re-registers (permanent class loss → infinite retry would also fail). In that case, bumping the budget is futile.

**Perturbation:** Read the retry loop and the catch list.

**Evidence (deduction, FaultTolerantWin32VirtualDesktopService.cs:100-125):**
```csharp
for (int i = 0; i < 10; i++)
{
    try { if (i != 0) { Thread.Sleep(500); m_vds.Connect(); } return func(); }
    catch (COMException e) when (e.HResult is RPC_S_SERVER_UNAVAILABLE
        or RPC_S_CALL_FAILED or REGDB_E_CLASSNOTREG or ERROR_INVALID_STATE) { ... }
}
```
- `REGDB_E_CLASSNOTREG` is explicitly in the catch filter — the design intent *is* to ride out transient unregistration windows.
- The exception that escapes is the same code, meaning all 10 retries observed the same condition.
- Sleep-wake on Win11 is known to delay Explorer COM re-registration (community reports, multiple OS builds).
- Maintainer (domain expert, wrote the code) concurs: "needs to be increased."

**Trajectory:** Convergent — the retry mechanism is correct in shape; budget is the variable.

**Provenance check:**
- `git blame` (via `gh api`): `FaultTolerantWin32VirtualDesktopService` predates the Win11 24H2/26100 changes; the 10×500ms heuristic was set when Explorer recoveries were typically sub-second.
- No open issues/PRs upstream propose a new budget.
- Adjacent clue: the void and generic overloads have duplicated retry bodies — bumping the budget requires editing both.

**Status:** Confirmed. Bumping the retry budget is the maintainer's preferred fix shape and is consistent with the evidence.

**Risk:** If a desktop call genuinely cannot succeed (e.g., Explorer crashed and won't return), longer retries delay the failure surface. Mitigation: cap total wait around 30s (still bounded), or use backoff so the common fast-recovery case isn't slower.

## H₂ — Async void UpdateLoop swallows the loop on any single failure (E2)

**Hypothesis:** Independent of the retry budget, *any* COMException not in the retry filter (or one that exceeds the budget) terminates the per-overlay update loop and crashes the dispatcher. Hardening upstream raises the bar but doesn't remove the failure mode.

**Null:** The dispatcher catches it gracefully and the loop self-recovers.

**Perturbation:** Read `OverlayHost.cs:136-144`.

**Evidence:**
- `async void UpdateLoop()` is not awaited. WPF's dispatcher unhandled-exception path is what the trace shows.
- One uncaught throw → the overlay never updates again until a Show()/restart.
- Compare: a `try { UpdatePositions(); } catch (COMException) { /* swallow, retry next tick */ }` would make a single 5s+ Explorer outage a single missed frame, not a crash.

**Trajectory:** Divergent.

**Status:** Partial — real, but **out of scope for the PR** the maintainer asked for. The maintainer scoped the fix to winman-windows. Filing a separate observation; do not bundle.

## Frontier

| Edge | Status | Next action |
|------|--------|-------------|
| H₁ retry budget | confirmed | propose minimal change to `FaultTolerantWin32VirtualDesktopService.cs` |
| H₂ async void loop | partial / deferred | mention in PR body as adjacent concern; do not fix here |

## Proposed fix shape (winman-windows)

Minimum change: raise retry count and/or add backoff so total budget covers post-resume Explorer recovery (~15–30s observed on Win11 26100+).

Two viable shapes:

**A. Bump iterations only (smallest diff):**
```csharp
for (int i = 0; i < 60; i++)   // ~30s at 500ms each
```

**B. Backoff (smaller idle cost, bounded tail):**
```csharp
for (int i = 0; i < 30; i++)
{
    try { if (i != 0) { Thread.Sleep(Math.Min(250 * i, 2000)); m_vds.Connect(); } return func(); }
    ...
}
// total worst case ~25s, fast common case still ~250ms first retry
```

Both must be applied to the `T` and `Action` overloads (DRY violation already present — leave as-is to minimize diff; extracting a helper is scope creep relative to maintainer's request).

## Reasoning mode table

| Claim | Mode | Confidence |
|-------|------|-----------:|
| Retry budget is 10 × 500ms | deduction (code read) | 99% |
| Sleep-wake delays Explorer COM re-registration | abduction + maintainer concurrence | 85% |
| Bumping budget eliminates this crash | abduction | 75% (no reproduction possible without sleep-wake on Win11 26100) |
| `async void` loop is a separate fragility | deduction | 95% |

## Halt point

Phase 5 (prework) is **not feasible** — the bug requires a Win11 26100+ machine with sleep-wake to reproduce, and the operator has no such environment. The fix is by-inspection against a maintainer-confirmed diagnosis, on a small bounded surface (one file, two overloads, constants only).

Recommendation: ship a minimal PR (option A) to winman-windows; reference issue #447; note that the `async void` loop fragility (H₂) remains and is tracked separately. Human gate at Phase 8.
