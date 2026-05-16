# Triage Graph: grafana/grafana (kimjune01)

**Scan date:** 2026-05-09

## Scan Table

| # | Title | State | Score | Effort | Signal | Status |
|---|-------|-------|-------|--------|--------|--------|
| — | Annotation tags column dropped when first item lacks tags | NO ISSUE | 6/10 | Small (~8 lines TS) | data loss bug | COMMITTED |

## Annotation tags missing from DataFrame

### Root Cause

`LegacyAnnotationServer.query()` passes the API response directly to `toDataFrame()`. `arrayToDataFrame` infers the schema from the first object's keys. When the first annotation object lacks a `tags` property (common for non-tagged annotations), the `tags` column is omitted from the DataFrame entirely — affecting all subsequent annotations that do have tags.

### Fix (~8 lines)

Backfill `tags` with an empty array on any annotation object missing it, before passing to `toDataFrame()`. File: `public/app/features/annotations/api.ts`.

### Narrowing (codex review)

Original fix backfilled ALL missing keys across all objects (union-schema approach). Codex recommended narrowing to just `tags` — it's the only known-affected field and a targeted fix avoids masking future schema issues from the API. Applied the narrow version.

### Competing PRs

None found targeting this specific bug.

### PR Viability: MODERATE

**For:** Clear data loss bug. Small, surgical fix. Well-documented API behavior. Grafana accepts external PRs and has `help wanted` labels.
**Against:** No open issue to reference. Large codebase with dedicated annotation team (`team/grafana-dashboards`). May prefer a fix at the `arrayToDataFrame` level in `@grafana/data` instead of caller-side.

### Risk

Moderate. Grafana has a formal review process and may redirect the fix to a different layer. Filing an issue first would strengthen the PR.

---

*Committed on branch `fix/annotation-tags-missing-field`. Ready to push.*
