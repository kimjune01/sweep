# Hypothesis graph: stacklok/toolhive-studio#2240

**Issue**: "Enterprise UI does not consume directives from /enterprise/api/v1beta/config"
**Reporter**: reyortiz3 (2026-05-13)
**Investigator**: kimjune01 / Opus 4.7
**Date**: 2026-05-18
**Status**: HALT — bug is outside this repo's surface

---

## H₀ — The OSS toolhive-studio repo contains the buggy `FH()` enterprise-config loader and a PR here can fix it

- **Null**: The loader (and the `/enterprise/api/v1beta/config` endpoint, and any code that translates directives → `PermissionsProvider value`) does not exist in this OSS repo; lives in a closed enterprise overlay.
- **Perturbation**: Grep the worktree for `/enterprise/api/v1beta`, `useQuery.*enterprise`, `queryKey.*enterprise`, `directive`, and `enterprise.*config`. Check whether `PermissionsProvider value` is wired to any data source.
- **Result**:
  - `enterprise/api/v1beta` / `v1beta/config`: **0 matches** in source. `common/api/openapi.json` exposes only `/api/v1beta/*` (workloads, registry, secrets, groups, skills, clients) — no `/enterprise/*` route.
  - `useQuery.*enterprise` / `queryKey.*enterprise` / `directive`: **0 matches**.
  - `PERMISSION_KEYS` exists in `renderer/src/common/contexts/permissions/permission-keys.ts` exactly as decompiled. `PermissionsProvider` exists with a `value?: Partial<Permissions>` slot — but the OSS build has **no caller** that supplies an enterprise-derived value; the slot is unused in OSS.
- **Trajectory**: **Divergent against H₀.** The OSS repo provides the permission-key surface (the *sink*) but contains none of the *source* code the issue describes — no `/enterprise/api/v1beta/config` endpoint, no `FH()` loader, no directive→permission mapping. Those live in the enterprise overlay build that wraps this app.
- **Kill condition**: zero matches for the described code in the worktree at `f3db57c`.

## Reasoning mode
- Deduction (read code, traced surface): 98% — confirmed by grep.

## Provenance
- `permission-keys.ts` matches the decompile verbatim (PR diff would be no-op).
- `permissions-provider.tsx` has a `value` slot ready for enterprise injection — consistent with the overlay-architecture hypothesis (OSS exposes seam, overlay populates it).
- The bug as written ("loader returns only `{state, warning, policy}`") cannot be reproduced or patched against any file in this repository.

## Decision
**Do not ship a PR to stacklok/toolhive-studio.** The fix belongs in the enterprise overlay repo where `FH()` and `getEnterpriseConfig` (`NH()` in the decompile) actually live. The OSS repo's contribution surface here is null.

If the operator wants a side-channel:
- A **tissue** comment to the maintainer confirming the gap was traced into the overlay (not OSS) and pointing at `PermissionsProvider value` as the intended seam may be appreciated, but adds nothing the reporter doesn't already document with more detail.
- More productive: nothing. Skip. Reporter is already specific; maintainer routing will happen internally.

## Frontier
None. Halt.
